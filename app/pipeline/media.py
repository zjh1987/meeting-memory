import shutil
import subprocess
from pathlib import Path

from app.providers.errors import ProviderError


def to_wav(src: Path, dst: Path) -> Path:
    if shutil.which("ffmpeg") is None:
        raise ProviderError("asr_unavailable", "未安装 FFmpeg")
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
           "-i", str(src), "-ar", "16000", "-ac", "1",
           "-c:a", "pcm_s16le", str(dst)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise ProviderError("asr_unavailable",
                            f"FFmpeg 转换失败：{result.stderr[:200]}")
    return dst


def duration_sec(path: Path) -> int:
    if shutil.which("ffprobe") is None:
        return 0
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration",
           "-of", "default=noprint_wrappers=1:nokey=1", str(path)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    try:
        return int(float(result.stdout.strip()))
    except (TypeError, ValueError):
        return 0
