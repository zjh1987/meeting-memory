from app.config import Config
from app.pipeline import media
from app.providers import build_asr
from app.providers.errors import ProviderError


def run(cfg: Config, meeting: dict, asr_settings: dict | None = None,
        max_duration_min: int | None = None) -> list[dict]:
    audio = cfg.ready_dir / meeting["audio_filename"]
    if not audio.exists():
        audio = cfg.archive_dir / meeting["audio_filename"]
    if not audio.exists():
        raise ProviderError("file_missing",
                            f"音频不存在：{meeting['audio_filename']}")

    provider = build_asr(cfg, asr_settings)
    backend = (asr_settings or {}).get("backend", cfg.asr_backend)
    if backend == "funasr":
        wav = media.to_wav(audio, cfg.ready_dir / f"{audio.stem}.16k.wav")
        try:
            limit = cfg.max_duration_min if max_duration_min is None else max_duration_min
            duration = media.wav_duration_sec(wav)
            if limit and duration > limit * 60:
                raise ProviderError(
                    "audio_too_long",
                    f"录音时长约 {duration / 60:.0f} 分钟，超过上限 {limit} 分钟")
            segments = provider.transcribe(wav)
        finally:
            wav.unlink(missing_ok=True)
    else:
        segments = provider.transcribe(audio)

    for index, segment in enumerate(segments):
        segment["idx"] = index
    return segments
