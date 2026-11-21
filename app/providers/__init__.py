from app.config import Config
from app.providers.asr_mock import MockAsr


def build_asr(cfg: Config, settings: dict | None = None):
    backend = (settings or {}).get("backend", cfg.asr_backend)
    if backend == "mock":
        return MockAsr()
    from app.providers.asr_funasr import FunAsrProvider
    return FunAsrProvider(cfg, settings)


def build_llm(cfg: Config, settings: dict | None = None):
    provider = (settings or {}).get("provider", cfg.llm_provider)
    if provider == "mock":
        from app.providers.llm_mock import MockLlm
        return MockLlm()
    from app.providers.llm_openai import OpenAiLlm
    return OpenAiLlm(cfg, settings)
