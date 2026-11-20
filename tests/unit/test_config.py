from dataclasses import replace

from app.config import Config


def test_from_env_reads_password_and_paths(cfg, tmp_path):
    assert cfg.app_password == "test-pass"
    assert cfg.db_path == (tmp_path / "data" / "app.db").resolve()
    assert cfg.inbox_dir.exists()
    assert cfg.ready_dir.exists()
    assert cfg.archive_dir.exists()


def test_validate_requires_password(cfg):
    broken = replace(cfg, app_password="")
    assert "APP_PASSWORD 未设置" in broken.validate()


def test_validate_requires_llm_settings_for_openai(cfg):
    broken = replace(cfg, llm_provider="openai", llm_base_url="", llm_model="")
    problems = broken.validate()
    assert any("LLM_BASE_URL" in p for p in problems)


def test_validate_requires_funasr_model_dir(cfg):
    broken = replace(cfg, asr_backend="funasr", funasr_model_dir=cfg.data_dir / "missing")
    problems = broken.validate()
    assert any("FUNASR_MODEL_DIR" in p for p in problems)
