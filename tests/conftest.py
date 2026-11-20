import sys
from dataclasses import replace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import Config


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "test-pass")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SITE_DIR", str(tmp_path / "site"))
    monkeypatch.setenv("LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("MIN_FREE_GB", "0")
    monkeypatch.setenv("FUNASR_MODEL_DIR", str(tmp_path / "models"))
    config = Config.from_env()
    config.ensure_dirs()
    from app.storage import db
    db.init_db(config.db_path, db.MIGRATIONS_DIR)
    return config


@pytest.fixture
def conn(cfg):
    from app.storage import db
    connection = db.connect(cfg.db_path)
    yield connection
    connection.close()
