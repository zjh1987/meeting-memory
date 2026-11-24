"""全局配置：全部来自环境变量，便于内网部署时调整。"""

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def _float(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


@dataclass(frozen=True)
class Config:
    app_password: str
    cookie_secret: str
    data_dir: Path
    site_dir: Path
    db_path: Path
    asr_backend: str
    funasr_model_dir: Path
    funasr_device: str
    hotword_file: Path
    llm_provider: str
    llm_base_url: str
    llm_api_key: str
    llm_model: str
    max_upload_mb: int
    min_free_gb: int
    scan_interval: int
    heartbeat_interval: int
    zombie_timeout: int
    auto_retry_max: int
    retry_backoff_sec: int
    speaker_threshold: float
    max_duration_min: int
    log_dir: Path

    @property
    def inbox_dir(self) -> Path:
        return self.data_dir / "inbox"

    @property
    def ready_dir(self) -> Path:
        return self.data_dir / "ready"

    @property
    def archive_dir(self) -> Path:
        return self.data_dir / "archive"

    @property
    def app_dir(self) -> Path:
        return self.data_dir / "app"

    @classmethod
    def from_env(cls) -> "Config":
        data_dir = Path(os.getenv("DATA_DIR", "./data")).resolve()
        site_dir = Path(os.getenv("SITE_DIR", "./site")).resolve()
        password = os.getenv("APP_PASSWORD", "")
        secret = os.getenv("COOKIE_SECRET", "")
        if not secret:
            # 未配置时由口令派生，保证重启后登录态不失效；生产建议显式设置。
            secret = hashlib.sha256(f"mm::{password}".encode()).hexdigest()
        return cls(
            app_password=password,
            cookie_secret=secret,
            data_dir=data_dir,
            site_dir=site_dir,
            db_path=Path(os.getenv("DB_PATH", str(data_dir / "app.db"))).resolve(),
            asr_backend=os.getenv("ASR_BACKEND", "mock"),
            funasr_model_dir=Path(os.getenv("FUNASR_MODEL_DIR", "./models/funasr")).resolve(),
            funasr_device=os.getenv("FUNASR_DEVICE", "cpu"),
            hotword_file=Path(os.getenv("HOTWORD_FILE", "./config/hotwords.txt")).resolve(),
            llm_provider=os.getenv("LLM_PROVIDER", "mock"),
            llm_base_url=os.getenv("LLM_BASE_URL", "").rstrip("/"),
            llm_api_key=os.getenv("LLM_API_KEY", ""),
            llm_model=os.getenv("LLM_MODEL", ""),
            max_upload_mb=_int("MAX_UPLOAD_MB", 1024),
            min_free_gb=_int("MIN_FREE_GB", 5),
            scan_interval=_int("SCAN_INTERVAL", 3),
            heartbeat_interval=_int("HEARTBEAT_INTERVAL", 60),
            zombie_timeout=_int("ZOMBIE_TIMEOUT", 180),
            auto_retry_max=_int("AUTO_RETRY_MAX", 1),
            retry_backoff_sec=_int("RETRY_BACKOFF_SEC", 30),
            speaker_threshold=_float("SPEAKER_THRESHOLD", 0.75),
            max_duration_min=_int("MAX_DURATION_MIN", 360),
            log_dir=Path(os.getenv("LOG_DIR", "./logs")).resolve(),
        )

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.inbox_dir, self.ready_dir,
                  self.archive_dir, self.app_dir, self.site_dir, self.log_dir):
            d.mkdir(parents=True, exist_ok=True)

    def validate(self) -> list[str]:
        problems: list[str] = []
        if not self.app_password:
            problems.append("APP_PASSWORD 未设置")
        if self.asr_backend not in {"mock", "funasr"}:
            problems.append(f"ASR_BACKEND 不支持：{self.asr_backend}")
        if self.asr_backend == "funasr" and not self.funasr_model_dir.exists():
            problems.append(f"FUNASR_MODEL_DIR 不存在：{self.funasr_model_dir}")
        if self.llm_provider not in {"mock", "openai"}:
            problems.append(f"LLM_PROVIDER 不支持：{self.llm_provider}")
        if self.llm_provider == "openai" and not (self.llm_base_url and self.llm_model):
            problems.append("LLM_BASE_URL 与 LLM_MODEL 必须设置")
        if self.max_upload_mb <= 0:
            problems.append("MAX_UPLOAD_MB 必须大于 0")
        if self.max_duration_min < 0:
            problems.append("MAX_DURATION_MIN 不能为负数")
        return problems
