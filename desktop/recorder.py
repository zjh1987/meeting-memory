"""16 kHz 单声道 WAV 录音与设备枚举。"""

import queue
import struct
import threading
import wave
from dataclasses import dataclass
from pathlib import Path

try:
    import numpy as np
    import sounddevice as sd
    AUDIO_IMPORT_ERROR = ""
except Exception as exc:  # 打包或缺少 PortAudio 时给出可读提示
    np = None
    sd = None
    AUDIO_IMPORT_ERROR = str(exc)

PREFERRED_RATE = 16000


class RecorderError(Exception):
    pass


@dataclass
class InputDevice:
    index: int
    key: str
    label: str
    max_channels: int
    default_rate: float


def list_input_devices() -> list[InputDevice]:
    if sd is None:
        raise RecorderError(f"音频组件不可用：{AUDIO_IMPORT_ERROR}")
    try:
        devices = sd.query_devices()
        hostapis = sd.query_hostapis()
        default_index = sd.default.device[0]
    except Exception as exc:
        raise RecorderError(f"无法读取录音设备：{exc}") from exc
    result: list[InputDevice] = []
    for index, device in enumerate(devices):
        if device.get("max_input_channels", 0) <= 0:
            continue
        host = hostapis[device["hostapi"]]["name"]
        key = f"{device['name']} · {host}"
        label = key + ("（系统默认）" if index == default_index else "")
        result.append(InputDevice(
            index=index,
            key=key,
            label=label,
            max_channels=int(device["max_input_channels"]),
            default_rate=float(device.get("default_samplerate") or 48000),
        ))
    return result


def default_device_key(devices: list[InputDevice]) -> str:
    for device in devices:
        if device.label.endswith("（系统默认）"):
            return device.key
    return devices[0].key if devices else ""


class WavRecorder:
    def __init__(self):
        self.state = "idle"
        self.path: Path | None = None
        self.rate = PREFERRED_RATE
        self.channels = 1
        self.frames = 0
        self.level = 0.0
        self.fallback_note = ""
        self.last_status = ""
        self._device_index: int | None = None
        self._stream = None
        self._wave: wave.Wave_write | None = None
        self._writer: threading.Thread | None = None
        self._queue: queue.Queue = queue.Queue()
        self._lock = threading.Lock()
        self._writer_error = ""

    @property
    def active(self) -> bool:
        return self.state in {"recording", "paused"}

    def elapsed(self) -> float:
        return self.frames / self.rate if self.rate else 0.0

    def start(self, path: Path, device_index: int,
              preferred_rate: int = PREFERRED_RATE) -> None:
        if self.state != "idle":
            raise RecorderError("当前已有录音正在进行")
        if sd is None or np is None:
            raise RecorderError(f"音频组件不可用：{AUDIO_IMPORT_ERROR}")
        self._reset()
        self.path = Path(path)
        self._device_index = device_index
        try:
            device = sd.query_devices(device_index)
        except Exception as exc:
            raise RecorderError(f"录音设备不可用：{exc}") from exc
        rate, channels, note = self._pick_settings(device, preferred_rate)
        self.rate = rate
        self.channels = channels
        self.fallback_note = note
        self._queue = queue.Queue()
        try:
            self._wave = wave.open(str(self.path), "wb")
            self._wave.setnchannels(1)
            self._wave.setsampwidth(2)
            self._wave.setframerate(rate)
        except OSError as exc:
            raise RecorderError(f"无法创建录音文件：{exc}") from exc
        self._writer = threading.Thread(target=self._writer_loop, daemon=True)
        self._writer.start()
        self.state = "recording"
        try:
            self._open_stream()
        except Exception:
            self._discard()
            raise

    def _pick_settings(self, device: dict, preferred_rate: int):
        max_channels = int(device.get("max_input_channels") or 1)
        default_rate = int(round(float(device.get("default_samplerate") or 48000)))
        candidates = [(preferred_rate, 1)]
        if default_rate != preferred_rate:
            candidates.append((default_rate, 1))
        if max_channels >= 2:
            candidates.append((default_rate, 2))
        for rate, channels in candidates:
            try:
                sd.check_input_settings(
                    device=self._device_index, channels=channels,
                    samplerate=rate, dtype="int16")
            except Exception:
                continue
            note = ""
            if rate != preferred_rate:
                note = f"设备不支持 {preferred_rate} Hz，已自动使用 {rate} Hz"
            elif channels != 1:
                note = "设备仅支持双声道，已自动混合为单声道"
            return rate, channels, note
        raise RecorderError("该设备不支持 16 kHz 或默认采样率录音，请更换输入设备")

    def _open_stream(self) -> None:
        try:
            self._stream = sd.InputStream(
                device=self._device_index,
                channels=self.channels,
                samplerate=self.rate,
                dtype="int16",
                callback=self._callback,
                blocksize=0,
            )
            self._stream.start()
        except Exception as exc:
            self._stream = None
            raise RecorderError(
                f"打开录音设备失败：{exc}\n"
                "请检查设备是否被其他软件占用，以及 Windows 设置 → 隐私 → "
                "麦克风是否允许桌面应用访问。") from exc

    def _callback(self, indata, frames, time_info, status) -> None:
        if self.state not in {"recording"}:
            return
        if status:
            self.last_status = str(status)
        try:
            if indata.ndim > 1 and indata.shape[1] > 1:
                mono = indata.astype("int32").mean(axis=1).astype("int16")
            else:
                mono = indata[:, 0] if indata.ndim > 1 else indata
            self._queue.put(mono.tobytes())
            self.frames += len(mono)
            peak = int(np.abs(mono).max()) if len(mono) else 0
            self.level = min(1.0, peak / 32768.0)
        except Exception as exc:
            self._writer_error = f"录音数据处理失败：{exc}"

    def _writer_loop(self) -> None:
        while True:
            chunk = self._queue.get()
            if chunk is None:
                break
            try:
                if self._wave is not None:
                    self._wave.writeframes(chunk)
            except Exception as exc:
                self._writer_error = f"写入录音文件失败：{exc}"
                break

    def pause(self) -> None:
        if self.state != "recording":
            return
        self._close_stream()
        self.state = "paused"

    def resume(self) -> None:
        if self.state != "paused":
            return
        self.state = "recording"
        try:
            self._open_stream()
        except Exception:
            self.state = "paused"
            raise

    def stop(self) -> float:
        if self.state == "idle":
            return 0.0
        self.state = "stopping"
        self._close_stream()
        self._queue.put(None)
        if self._writer is not None:
            self._writer.join(timeout=10)
        if self._wave is not None:
            try:
                self._wave.close()
            except Exception:
                pass
        duration = self.elapsed()
        if self._writer_error:
            message = self._writer_error
            self._reset()
            raise RecorderError(message)
        self.state = "idle"
        return duration

    def shutdown(self) -> None:
        try:
            if self.active:
                self.stop()
        except Exception:
            pass

    def _discard(self) -> None:
        self.state = "idle"
        self._close_stream()
        try:
            self._queue.put(None)
        except Exception:
            pass
        if self._writer is not None:
            self._writer.join(timeout=2)
        if self._wave is not None:
            try:
                self._wave.close()
            except Exception:
                pass
        if self.path is not None:
            try:
                self.path.unlink(missing_ok=True)
            except OSError:
                pass
        self._wave = None
        self._writer = None
        self.path = None

    def _close_stream(self) -> None:
        with self._lock:
            if self._stream is not None:
                try:
                    self._stream.stop()
                except Exception:
                    pass
                try:
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None

    def _reset(self) -> None:
        self.state = "idle"
        self.frames = 0
        self.level = 0.0
        self.last_status = ""
        self._writer_error = ""
        self._stream = None
        self._wave = None
        self._writer = None
        self._queue = queue.Queue()


def repair_wav(path: Path) -> bool:
    """进程异常退出后，按实际文件长度修正 WAV 头。"""
    try:
        size = path.stat().st_size
        if size <= 44:
            return False
        with path.open("r+b") as handle:
            header = handle.read(44)
            if header[:4] != b"RIFF" or header[8:12] != b"WAVE":
                return False
            if header[36:40] != b"data":
                return False
            handle.seek(4)
            handle.write(struct.pack("<I", size - 8))
            handle.seek(40)
            handle.write(struct.pack("<I", size - 44))
        return True
    except OSError:
        return False
