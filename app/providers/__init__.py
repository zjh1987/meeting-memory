from app.config import Config
from app.providers.asr_mock import MockAsr


def build_asr(cfg: Config):
    if cfg.asr_backend == "mock":
        return MockAsr()
    from app.providers.asr_funasr import FunAsrProvider
    return FunAsrProvider(cfg)


def build_llm(cfg: Config):
    if cfg.llm_provider == "mock":
        from app.providers.llm_mock import MockLlm
        return MockLlm()
    from app.providers.llm_openai import OpenAiLlm
    return OpenAiLlm(cfg)
