"""本地配置、登录会话与录音目录。"""

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

APP_NAME = "MeetingMemoryRecorder"


def app_home() -> Path:
    override = os.environ.get("MEETING_MEMORY_HOME")
    base = Path(override) if override else Path(os.environ.get("APPDATA", Path.home()))
    home = base / APP_NAME if not override else base
    home.mkdir(parents=True, exist_ok=True)
    return home


def recordings_dir() -> Path:
    folder = app_home() / "recordings"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def logs_dir() -> Path:
    folder = app_home() / "logs"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _config_path() -> Path:
    return app_home() / "config.json"


def _session_path() -> Path:
    return app_home() / "session.json"


@dataclass
class AppConfig:
    server: str = "http://192.168.110.14:8000"
    username: str = "admin"
    remember: bool = True
    trust_self_signed: bool = False
    device: str = ""
    project: str = ""
    template: str = ""
    geometry: str = ""


def load_config() -> AppConfig:
    path = _config_path()
    if not path.is_file():
        return AppConfig()
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return AppConfig()
    config = AppConfig()
    for field_name in config.__dataclass_fields__:
        if field_name in data:
            setattr(config, field_name, data[field_name])
    return config


def save_config(config: AppConfig) -> None:
    _write_json(_config_path(), asdict(config))


def load_session() -> dict | None:
    path = _session_path()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not data.get("cookie"):
        return None
    return data


def save_session(cookie: str, host: str, username: str) -> None:
    _write_json(_session_path(), {
        "cookie": cookie,
        "host": host,
        "username": username,
    })


def clear_session() -> None:
    try:
        _session_path().unlink(missing_ok=True)
    except OSError:
        pass


def _write_json(path: Path, data: dict) -> None:
    part = path.with_name(path.name + ".part")
    part.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    os.replace(str(part), str(path))
