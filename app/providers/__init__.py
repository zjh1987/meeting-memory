from app.config import Config
from app.providers.asr_mock import MockAsr


def build_asr(cfg: Config):
    if cfg.asr_backend == "mock":
        return MockAsr()
    from app.providers.asr_funasr import FunAsrProvider
    return FunAsrProvider(cfg)
