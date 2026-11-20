from app.config import Config
from app.pipeline import media
from app.providers import build_asr
from app.providers.errors import ProviderError


def run(cfg: Config, meeting: dict) -> list[dict]:
    audio = cfg.ready_dir / meeting["audio_filename"]
    if not audio.exists():
        audio = cfg.archive_dir / meeting["audio_filename"]
    if not audio.exists():
        raise ProviderError("file_missing",
                            f"音频不存在：{meeting['audio_filename']}")

    provider = build_asr(cfg)
    if cfg.asr_backend == "funasr":
        wav = media.to_wav(audio, cfg.ready_dir / f"{audio.stem}.16k.wav")
        try:
            segments = provider.transcribe(wav)
        finally:
            wav.unlink(missing_ok=True)
    else:
        segments = provider.transcribe(audio)

    for index, segment in enumerate(segments):
        segment["idx"] = index
    return segments
