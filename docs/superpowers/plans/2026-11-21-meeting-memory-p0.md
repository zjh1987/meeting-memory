# 会议记忆系统 P0 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 按已确认的开发规格，重写并交付可内网私有化部署的会议记忆系统 P0：上传/落盘采集、自动转写与分人、结构化纪要、跨会议关联、静态归档。

**Architecture:** FastAPI 单进程 + SQLite（WAL）+ 三个后台线程（Harvester / Worker / Maintainer）；会议表本身充当任务队列，状态机条件更新保证不重复处理；音频以 `.part` + rename 原子落盘；ASR/LLM 均通过 Provider 接口隔离，mock 可离线跑通全链路。

**Tech Stack:** Python 3.10、FastAPI、Jinja2、SQLite、httpx、pytest、FFmpeg、FunASR（paraformer-zh + fsmn-vad + ct-punc + cam++）。

**依据规格：** `docs/superpowers/specs/2026-11-20-meeting-memory-design.md`

---

## 执行前须知

- 工作目录：`d:\FP\omarchy\temp_20261118_01`，Windows PowerShell 5。
- 每个任务结束都提交一次；提交前必须让该任务的全部测试通过。
- 任务 1 会归档现有原型（`app.py`、`pipeline.py` 等）到 `legacy/`。执行前先停掉正在运行的原型服务（占用 `data/app.db`）。
- 所有命令都在仓库根目录执行，不要 `cd` 到子目录。
- FFmpeg 只在真实 FunASR 模式下需要；mock 链路不需要，单元测试不得依赖它。

## 文件地图（最终形态）

```
app/
  main.py                    配置装配、路由注册、lifespan 启线程
  config.py                  环境变量读取与校验
  api/
    errors.py                ApiError 与统一错误响应
    auth.py                  令牌、登录限流、登录/登出路由
    upload.py                上传接口
    projects.py              项目列表接口
    meetings.py              会议列表/状态/重试接口
  core/
    state.py                 状态集合、合法迁移、恢复点、可重试判断
    similarity.py            字符二元组 Jaccard
  storage/
    db.py                    连接（WAL/autocommit）与迁移执行
    migrations/001_init.sql  建表与种子项目
    project_repo.py
    meeting_repo.py
    action_repo.py
    relation_repo.py
    files.py                 原子落盘、文件名清洗、磁盘水位
  providers/
    errors.py                ProviderError（code/transient）
    base.py                  ASR / LLM 两个 Protocol
    asr_mock.py
    asr_funasr.py
    llm_mock.py
    llm_openai.py
  pipeline/
    media.py                 ffmpeg/ffprobe 封装
    transcribe.py            转写阶段
    minutes.py               Prompt、分块、校验、合并
    relations.py             两类关联规则
    archive.py               静态归档与索引
    harvester.py             inbox → ready
    maintainer.py            僵尸回收、残片清理
    worker.py                领取任务、阶段推进、心跳、重试
  web/
    render.py                Jinja 环境
    context.py               详情页上下文（模板区块、待办、关联）
    pages.py                 页面路由
    templates/
      _style.html
      base.html
      login.html
      index.html
      meeting.html
      day_index.html
      root_index.html
deploy/
  systemd/mm.service
  nginx/mm.conf
  backup.sh
  delete_meeting.py
config/hotwords.txt
tests/
  conftest.py
  unit/...
  integration/...
```

---

# M0 工程骨架

### Task 1: 仓库初始化、原型归档、依赖清单

**Files:**
- Create: `.gitignore`, `requirements.txt`, `requirements-dev.txt`, `requirements-asr.txt`, `.env.example`
- Move: 原型文件到 `legacy/`

- [ ] **Step 1: 停止原型服务并初始化仓库**

```powershell
# 如果上一个会话的服务还在跑，先停掉（占用 data/app.db）
Get-CimInstance Win32_Process -Filter "name='python.exe'" |
  Where-Object { $_.CommandLine -match 'uvicorn|app\.py' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
git init
```

预期：`Initialized empty Git repository in ...`

- [ ] **Step 2: 归档原型文件**

```powershell
New-Item -ItemType Directory -Force legacy | Out-Null
Move-Item app.py,pipeline.py,providers.py,render.py,store.py,config.py legacy
Move-Item templates legacy\templates
Move-Item data legacy\data
Move-Item site legacy\site
Remove-Item __pycache__ -Recurse -Force -ErrorAction SilentlyContinue
```

预期：根目录只剩 `legacy/`、`docs/`、`.screenshots/` 等。

- [ ] **Step 3: 写依赖与忽略文件**

`.gitignore`：

```gitignore
__pycache__/
*.pyc
.pytest_cache/
.env
data/
site/
logs/
models/
.screenshots/
legacy/data/
legacy/site/
```

`requirements.txt`：

```text
fastapi>=0.110,<1
uvicorn[standard]>=0.29,<1
jinja2>=3.1,<4
python-multipart>=0.0.9
httpx>=0.27,<1
```

`requirements-dev.txt`：

```text
-r requirements.txt
pytest>=8
```

`requirements-asr.txt`：

```text
funasr>=1.1
torch
torchaudio
modelscope
```

`.env.example`：

```text
APP_PASSWORD=change-me
COOKIE_SECRET=
DATA_DIR=./data
SITE_DIR=./site
ASR_BACKEND=mock
FUNASR_MODEL_DIR=./models/funasr
FUNASR_DEVICE=cpu
HOTWORD_FILE=./config/hotwords.txt
LLM_PROVIDER=mock
LLM_BASE_URL=
LLM_API_KEY=
LLM_MODEL=
MAX_UPLOAD_MB=500
MIN_FREE_GB=5
SCAN_INTERVAL=3
HEARTBEAT_INTERVAL=60
ZOMBIE_TIMEOUT=180
AUTO_RETRY_MAX=1
RETRY_BACKOFF_SEC=30
SPEAKER_THRESHOLD=0.75
LOG_DIR=./logs
```

- [ ] **Step 4: 安装依赖并验证**

```powershell
python -m pip install -r requirements.txt -r requirements-dev.txt
python -c "import fastapi, jinja2, httpx, multipart, pytest; print('deps ok')"
```

预期：`deps ok`。若公司内网有镜像，加 `-i https://pypi.tuna.tsinghua.edu.cn/simple`。

- [ ] **Step 5: 首次提交**

```powershell
git add -A
git commit -m "chore: 初始化仓库并归档 v0 原型"
```

---

### Task 2: 配置加载与校验

**Files:**
- Create: `app/__init__.py`（空文件）、`app/config.py`
- Test: `tests/conftest.py`、`tests/unit/test_config.py`

- [ ] **Step 1: 写失败的测试**

`tests/conftest.py`：

```python
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
    return config
```

`tests/unit/test_config.py`：

```python
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
```

- [ ] **Step 2: 运行测试确认失败**

```powershell
python -m pytest tests/unit/test_config.py -v
```

预期：`ModuleNotFoundError: No module named 'app'` 或 `ImportError: cannot import name 'Config'`。

- [ ] **Step 3: 实现配置**

创建空文件 `app/__init__.py`，然后写 `app/config.py`：

```python
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
            max_upload_mb=_int("MAX_UPLOAD_MB", 500),
            min_free_gb=_int("MIN_FREE_GB", 5),
            scan_interval=_int("SCAN_INTERVAL", 3),
            heartbeat_interval=_int("HEARTBEAT_INTERVAL", 60),
            zombie_timeout=_int("ZOMBIE_TIMEOUT", 180),
            auto_retry_max=_int("AUTO_RETRY_MAX", 1),
            retry_backoff_sec=_int("RETRY_BACKOFF_SEC", 30),
            speaker_threshold=_float("SPEAKER_THRESHOLD", 0.75),
            log_dir=Path(os.getenv("LOG_DIR", "./logs")).resolve(),
        )

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.inbox_dir, self.ready_dir,
                  self.archive_dir, self.site_dir, self.log_dir):
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
        return problems
```

- [ ] **Step 4: 运行测试确认通过**

```powershell
python -m pytest tests/unit/test_config.py -v
```

预期：4 passed。

- [ ] **Step 5: 提交**

```powershell
git add app/__init__.py app/config.py tests/
git commit -m "feat: 配置加载与启动校验"
```

---

### Task 3: 数据库连接与迁移

**Files:**
- Create: `app/storage/__init__.py`（空）、`app/storage/db.py`、`app/storage/migrations/001_init.sql`
- Modify: `tests/conftest.py`（增加数据库初始化与 `conn` fixture）
- Test: `tests/unit/test_db.py`

- [ ] **Step 1: 写失败的测试**

`tests/unit/test_db.py`：

```python
from app.storage import db


def test_init_db_creates_tables_and_seed_project(cfg):
    conn = db.connect(cfg.db_path)
    try:
        names = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"project", "meeting", "action_item", "relation"} <= names
        seed = conn.execute("SELECT id FROM project WHERE name='未归类'").fetchone()
        assert seed is not None
    finally:
        conn.close()


def test_init_db_is_idempotent(cfg):
    db.init_db(cfg.db_path, db.MIGRATIONS_DIR)
    db.init_db(cfg.db_path, db.MIGRATIONS_DIR)
    conn = db.connect(cfg.db_path)
    row = conn.execute("SELECT COUNT(*) AS n FROM schema_version").fetchone()
    assert row["n"] == 1
    conn.close()
```

- [ ] **Step 2: 运行测试确认失败**

```powershell
python -m pytest tests/unit/test_db.py -v
```

预期：`ModuleNotFoundError: No module named 'app.storage'`。

- [ ] **Step 3: 实现连接、迁移与建表 SQL**

`app/storage/__init__.py` 为空文件。`app/storage/db.py`：

```python
"""SQLite 连接与迁移。autocommit 模式，事务由调用方显式 BEGIN/COMMIT。"""

import sqlite3
from datetime import datetime
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=5, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: Path, migrations_dir: Path = MIGRATIONS_DIR) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(db_path)
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_version ("
            " version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        for path in sorted(migrations_dir.glob("*.sql")):
            version = path.stem
            exists = conn.execute(
                "SELECT 1 FROM schema_version WHERE version=?", (version,)
            ).fetchone()
            if exists:
                continue
            conn.executescript(path.read_text(encoding="utf-8"))
            conn.execute(
                "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                (version, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            )
    finally:
        conn.close()
```

`app/storage/migrations/001_init.sql`：

```sql
CREATE TABLE IF NOT EXISTS project (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS meeting (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    uid            TEXT NOT NULL UNIQUE,
    title          TEXT NOT NULL,
    project_id     INTEGER NOT NULL REFERENCES project(id),
    template_key   TEXT NOT NULL DEFAULT 'standard',
    recorded_at    TEXT NOT NULL,
    duration_sec   INTEGER NOT NULL DEFAULT 0,
    audio_filename TEXT NOT NULL,
    audio_size     INTEGER NOT NULL DEFAULT 0,
    status         TEXT NOT NULL DEFAULT 'pending',
    error_code     TEXT,
    error_msg      TEXT,
    retry_count    INTEGER NOT NULL DEFAULT 0,
    next_retry_at  TEXT,
    transcript     TEXT,
    minutes        TEXT,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL,
    started_at     TEXT,
    finished_at    TEXT,
    heartbeat_at   TEXT
);

CREATE TABLE IF NOT EXISTS action_item (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    meeting_id  INTEGER NOT NULL REFERENCES meeting(id),
    owner       TEXT,
    task        TEXT NOT NULL,
    due         TEXT,
    quote       TEXT NOT NULL,
    segment_ids TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'open',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS relation (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    meeting_id INTEGER NOT NULL REFERENCES meeting(id),
    target_id  INTEGER NOT NULL REFERENCES meeting(id),
    kind       TEXT NOT NULL,
    detail     TEXT NOT NULL,
    quote      TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_meeting_project  ON meeting(project_id);
CREATE INDEX IF NOT EXISTS idx_meeting_status   ON meeting(status);
CREATE INDEX IF NOT EXISTS idx_meeting_recorded ON meeting(recorded_at);
CREATE INDEX IF NOT EXISTS idx_action_meeting   ON action_item(meeting_id);
CREATE INDEX IF NOT EXISTS idx_action_status    ON action_item(status);
CREATE INDEX IF NOT EXISTS idx_relation_meeting ON relation(meeting_id);

INSERT OR IGNORE INTO project (name, created_at)
VALUES ('未归类', datetime('now', 'localtime'));
```

修改 `tests/conftest.py`，把 `cfg` fixture 末尾改为同时初始化数据库，并增加 `conn` fixture：

```python
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
```

- [ ] **Step 4: 运行测试确认通过**

```powershell
python -m pytest tests/unit/test_db.py -v
```

预期：2 passed。

- [ ] **Step 5: 提交**

```powershell
git add app/storage tests/conftest.py tests/unit/test_db.py
git commit -m "feat: SQLite 连接与迁移骨架"
```

---

### Task 4: 状态机、恢复点与可重试判断

**Files:**
- Create: `app/core/__init__.py`（空）、`app/core/state.py`
- Test: `tests/unit/test_state.py`

- [ ] **Step 1: 写失败的测试**

`tests/unit/test_state.py`：

```python
from app.core import state


def test_legal_transitions():
    assert state.can_transition("uploading", "pending")
    assert state.can_transition("pending", "transcribing")
    assert state.can_transition("pending", "failed")
    assert state.can_transition("transcribing", "minuting")
    assert state.can_transition("transcribing", "relating")
    assert state.can_transition("minuting", "done")
    assert state.can_transition("done", "failed")
    assert state.can_transition("failed", "pending")
    assert state.can_transition("done", "pending")


def test_illegal_transitions():
    assert not state.can_transition("pending", "done")
    assert not state.can_transition("uploading", "minuting")
    assert not state.can_transition("done", "transcribing")


def test_resume_stage():
    assert state.resume_stage(None, None) == "transcribe"
    assert state.resume_stage("[]", None) == "minutes"
    assert state.resume_stage("[]", "{}") == "relations"


def test_can_retry():
    assert state.can_retry({"status": "failed", "minutes": None})
    assert state.can_retry({"status": "done", "minutes": None})
    assert not state.can_retry({"status": "done", "minutes": "{}"})
    assert not state.can_retry({"status": "transcribing", "minutes": None})
```

- [ ] **Step 2: 运行测试确认失败**

```powershell
python -m pytest tests/unit/test_state.py -v
```

预期：`ModuleNotFoundError: No module named 'app.core'`。

- [ ] **Step 3: 实现状态机**

`app/core/__init__.py` 为空文件。`app/core/state.py`：

```python
"""会议状态机。所有状态推进都必须先过 can_transition。"""

STATUS_LABELS = {
    "uploading": "接收中",
    "pending": "排队中",
    "transcribing": "转写中",
    "minuting": "生成纪要中",
    "relating": "归档中",
    "done": "已完成",
    "failed": "处理失败",
}

PROCESSING = ("transcribing", "minuting", "relating")

_ALLOWED = {
    ("uploading", "pending"),
    ("uploading", "failed"),
    ("pending", "transcribing"),
    ("pending", "failed"),
    ("transcribing", "minuting"),
    ("transcribing", "relating"),
    ("transcribing", "pending"),
    ("transcribing", "failed"),
    ("minuting", "relating"),
    ("minuting", "done"),
    ("minuting", "pending"),
    ("minuting", "failed"),
    ("relating", "done"),
    ("relating", "pending"),
    ("failed", "pending"),
    ("done", "failed"),
    ("done", "pending"),
}


def can_transition(src: str, dst: str) -> bool:
    return (src, dst) in _ALLOWED


def resume_stage(transcript: str | None, minutes: str | None) -> str:
    """根据已有产物决定从哪一步继续，避免重试时重复调用 ASR。"""
    if not transcript:
        return "transcribe"
    if not minutes:
        return "minutes"
    return "relations"


def can_retry(meeting: dict) -> bool:
    status = meeting["status"]
    if status == "failed":
        return True
    return status == "done" and not meeting.get("minutes")
```

- [ ] **Step 4: 运行测试确认通过**

```powershell
python -m pytest tests/unit/test_state.py -v
```

预期：4 passed。

- [ ] **Step 5: 提交**

```powershell
git add app/core tests/unit/test_state.py
git commit -m "feat: 会议状态机与恢复点"
```

---

### Task 5: 项目与会议仓储

**Files:**
- Create: `app/storage/project_repo.py`、`app/storage/meeting_repo.py`
- Test: `tests/unit/test_repos_meeting.py`

- [ ] **Step 1: 写失败的测试**

`tests/unit/test_repos_meeting.py`：

```python
from app.storage import meeting_repo, project_repo


def _create(conn, uid="20261121-100000-abcd", title="测试会", project="项目A", status="pending"):
    pid = project_repo.ensure_project(conn, project)
    return meeting_repo.create(
        conn, uid=uid, title=title, project_id=pid,
        recorded_at="2026-11-21 10:00:00", audio_filename=f"{uid}__{title}.m4a",
        audio_size=1024, status=status,
    )


def test_ensure_project_reuses_existing(conn):
    a = project_repo.ensure_project(conn, "项目A")
    b = project_repo.ensure_project(conn, "项目A")
    assert a == b
    assert {p["name"] for p in project_repo.list_all(conn)} >= {"项目A", "未归类"}


def test_create_and_get(conn):
    _create(conn)
    m = meeting_repo.get_by_uid(conn, "20261121-100000-abcd")
    assert m["title"] == "测试会"
    assert m["status"] == "pending"


def test_list_page_filters(conn):
    _create(conn, uid="u1", project="项目A")
    _create(conn, uid="u2", project="项目B")
    pid_a = project_repo.ensure_project(conn, "项目A")
    items, total = meeting_repo.list_page(conn, project_id=pid_a)
    assert total == 1
    assert items[0]["uid"] == "u1"
    assert items[0]["project_name"] == "项目A"


def test_claim_next_moves_to_transcribing(conn):
    _create(conn, uid="u1")
    _create(conn, uid="u2")
    first = meeting_repo.claim_next(conn, "2026-11-21 10:00:00")
    second = meeting_repo.claim_next(conn, "2026-11-21 10:00:00")
    third = meeting_repo.claim_next(conn, "2026-11-21 10:00:00")
    assert first["uid"] == "u1"
    assert second["uid"] == "u2"
    assert third is None
    assert meeting_repo.get_by_uid(conn, "u1")["status"] == "transcribing"


def test_claim_respects_next_retry_at(conn):
    _create(conn, uid="u1")
    conn.execute("UPDATE meeting SET next_retry_at='2026-11-21 11:00:00'")
    assert meeting_repo.claim_next(conn, "2026-11-21 10:00:00") is None
    assert meeting_repo.claim_next(conn, "2026-11-21 11:00:01")["uid"] == "u1"


def test_set_status_and_reset_for_retry(conn):
    _create(conn, uid="u1")
    m = meeting_repo.get_by_uid(conn, "u1")
    meeting_repo.set_status(conn, m["id"], "failed", "asr_timeout", "超时")
    assert meeting_repo.get_by_uid(conn, "u1")["finished_at"] is not None
    meeting_repo.reset_for_retry(conn, m["id"])
    fresh = meeting_repo.get_by_uid(conn, "u1")
    assert fresh["status"] == "pending"
    assert fresh["finished_at"] is None
    assert fresh["retry_count"] == 1
```

- [ ] **Step 2: 运行测试确认失败**

```powershell
python -m pytest tests/unit/test_repos_meeting.py -v
```

预期：`ImportError` 或 `AttributeError`。

- [ ] **Step 3: 实现两个仓储**

`app/storage/project_repo.py`：

```python
import sqlite3
from datetime import datetime


def ensure_project(conn: sqlite3.Connection, name: str) -> int:
    name = name.strip() or "未归类"
    row = conn.execute("SELECT id FROM project WHERE name=?", (name,)).fetchone()
    if row:
        return int(row["id"])
    cur = conn.execute(
        "INSERT INTO project (name, created_at) VALUES (?, ?)",
        (name, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
    )
    return int(cur.lastrowid)


def list_all(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT * FROM project ORDER BY id").fetchall()
    return [dict(r) for r in rows]
```

`app/storage/meeting_repo.py`：

```python
"""会议仓储。claim_next 用 BEGIN IMMEDIATE + 条件更新保证不重复领取。"""

import sqlite3
from datetime import datetime

from app.core import state

FIELDS = {
    "title", "project_id", "template_key", "recorded_at", "duration_sec",
    "audio_filename", "audio_size", "status", "error_code", "error_msg",
    "retry_count", "next_retry_at", "transcript", "minutes",
    "started_at", "finished_at", "heartbeat_at",
}


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def create(conn, *, uid, title, project_id, recorded_at, audio_filename,
           audio_size=0, template_key="standard", status="pending") -> int:
    ts = now_str()
    cur = conn.execute(
        "INSERT INTO meeting (uid, title, project_id, template_key, recorded_at,"
        " audio_filename, audio_size, status, created_at, updated_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?)",
        (uid, title, project_id, template_key, recorded_at,
         audio_filename, audio_size, status, ts, ts),
    )
    return int(cur.lastrowid)


def get_by_uid(conn, uid: str) -> dict | None:
    row = conn.execute("SELECT * FROM meeting WHERE uid=?", (uid,)).fetchone()
    return dict(row) if row else None


def get_by_id(conn, meeting_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM meeting WHERE id=?", (meeting_id,)).fetchone()
    return dict(row) if row else None


def list_page(conn, project_id=None, status=None, date=None, page=1, size=20):
    where, params = [], []
    if project_id:
        where.append("m.project_id=?")
        params.append(project_id)
    if status:
        where.append("m.status=?")
        params.append(status)
    if date:
        where.append("substr(m.recorded_at,1,10)=?")
        params.append(date)
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    total = conn.execute(
        f"SELECT COUNT(*) AS n FROM meeting m{clause}", params
    ).fetchone()["n"]
    offset = max(page - 1, 0) * size
    rows = conn.execute(
        f"SELECT m.*, p.name AS project_name,"
        f" (SELECT COUNT(*) FROM action_item a"
        f"  WHERE a.meeting_id=m.id AND a.status='open') AS open_actions"
        f" FROM meeting m JOIN project p ON p.id=m.project_id{clause}"
        f" ORDER BY m.recorded_at DESC, m.id DESC LIMIT ? OFFSET ?",
        params + [size, offset],
    ).fetchall()
    return [dict(r) for r in rows], int(total)


def claim_next(conn, at: str | None = None) -> dict | None:
    at = at or now_str()
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute(
            "SELECT * FROM meeting WHERE status='pending'"
            " AND (next_retry_at IS NULL OR next_retry_at<=?)"
            " ORDER BY id LIMIT 1",
            (at,),
        ).fetchone()
        if row is None:
            conn.execute("COMMIT")
            return None
        cur = conn.execute(
            "UPDATE meeting SET status='transcribing', started_at=?,"
            " heartbeat_at=?, updated_at=?, error_code=NULL, error_msg=NULL"
            " WHERE id=? AND status='pending'",
            (at, at, at, row["id"]),
        )
        if cur.rowcount != 1:
            conn.execute("ROLLBACK")
            return None
        conn.execute("COMMIT")
        claimed = dict(row)
        claimed.update(status="transcribing", started_at=at, heartbeat_at=at)
        return claimed
    except Exception:
        conn.execute("ROLLBACK")
        raise


def set_status(conn, meeting_id: int, status: str,
               error_code: str | None = None,
               error_msg: str | None = None) -> None:
    row = conn.execute("SELECT status FROM meeting WHERE id=?",
                       (meeting_id,)).fetchone()
    if row and not state.can_transition(row["status"], status):
        raise ValueError(f"非法状态迁移：{row['status']} -> {status}")
    ts = now_str()
    if status in {"done", "failed"}:
        conn.execute(
            "UPDATE meeting SET status=?, error_code=?, error_msg=?,"
            " finished_at=?, updated_at=? WHERE id=?",
            (status, error_code, error_msg, ts, ts, meeting_id),
        )
    elif status == "pending":
        conn.execute(
            "UPDATE meeting SET status=?, error_code=?, error_msg=?,"
            " finished_at=NULL, updated_at=? WHERE id=?",
            (status, error_code, error_msg, ts, meeting_id),
        )
    else:
        conn.execute(
            "UPDATE meeting SET status=?, error_code=?, error_msg=?,"
            " updated_at=? WHERE id=?",
            (status, error_code, error_msg, ts, meeting_id),
        )


def update_fields(conn, meeting_id: int, **fields) -> None:
    unknown = set(fields) - FIELDS
    if unknown:
        raise ValueError(f"不允许更新的字段：{unknown}")
    if not fields:
        return
    fields["updated_at"] = now_str()
    assigns = ", ".join(f"{k}=?" for k in fields)
    conn.execute(
        f"UPDATE meeting SET {assigns} WHERE id=?",
        list(fields.values()) + [meeting_id],
    )


def touch(conn, meeting_id: int) -> None:
    conn.execute(
        "UPDATE meeting SET heartbeat_at=?, updated_at=? WHERE id=?",
        (now_str(), now_str(), meeting_id),
    )


def reset_for_retry(conn, meeting_id: int) -> None:
    ts = now_str()
    conn.execute(
        "UPDATE meeting SET status='pending', error_code=NULL, error_msg=NULL,"
        " next_retry_at=NULL, finished_at=NULL, started_at=NULL, heartbeat_at=NULL,"
        " retry_count=retry_count+1, updated_at=? WHERE id=?",
        (ts, meeting_id),
    )


def previous_done(conn, project_id: int, before_id: int, limit: int = 5) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM meeting WHERE project_id=? AND id<? AND status='done'"
        " ORDER BY id DESC LIMIT ?",
        (project_id, before_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]
```

- [ ] **Step 4: 运行测试确认通过**

```powershell
python -m pytest tests/unit/test_repos_meeting.py -v
```

预期：6 passed。

- [ ] **Step 5: 提交**

```powershell
git add app/storage/project_repo.py app/storage/meeting_repo.py tests/unit/test_repos_meeting.py
git commit -m "feat: 项目与会议仓储、任务领取"
```

---

### Task 6: 待办与关联仓储

**Files:**
- Create: `app/storage/action_repo.py`、`app/storage/relation_repo.py`
- Test: `tests/unit/test_repos_relation.py`

- [ ] **Step 1: 写失败的测试**

`tests/unit/test_repos_relation.py`：

```python
from app.storage import action_repo, meeting_repo, project_repo, relation_repo


def _meeting(conn, uid="u1"):
    pid = project_repo.ensure_project(conn, "项目A")
    return meeting_repo.create(
        conn, uid=uid, title="会", project_id=pid,
        recorded_at="2026-11-21 10:00:00", audio_filename=f"{uid}.m4a",
    )


def test_replace_and_read_actions(conn):
    mid = _meeting(conn)
    action_repo.replace(conn, mid, [
        {"owner": "张敏", "task": "整理问题清单", "due": "下周",
         "quote": "我下周先把问题清单整理出来", "segment_ids": [3]},
    ])
    rows = action_repo.list_for(conn, mid)
    assert len(rows) == 1
    assert rows[0]["segment_ids"] == [3]
    assert rows[0]["status"] == "open"


def test_open_for_only_returns_open(conn):
    mid = _meeting(conn)
    action_repo.replace(conn, mid, [
        {"owner": "A", "task": "t1", "due": "", "quote": "q1", "segment_ids": [0]},
        {"owner": "B", "task": "t2", "due": "", "quote": "q2", "segment_ids": [1]},
    ])
    conn.execute("UPDATE action_item SET status='done' WHERE task='t2'")
    rows = action_repo.open_for(conn, mid)
    assert [r["task"] for r in rows] == ["t1"]


def test_relations_join_target_meeting(conn):
    a = _meeting(conn, uid="u1")
    b = _meeting(conn, uid="u2")
    relation_repo.replace(conn, b, [
        {"target_id": a, "kind": "repeat_topic", "detail": "议题重复", "quote": "预算"},
    ])
    rows = relation_repo.list_for(conn, b)
    assert rows[0]["target_uid"] == "u1"
    assert rows[0]["target_title"] == "会"
```

- [ ] **Step 2: 运行测试确认失败**

```powershell
python -m pytest tests/unit/test_repos_relation.py -v
```

预期：`ModuleNotFoundError: No module named 'app.storage.action_repo'`。

- [ ] **Step 3: 实现两个仓储**

`app/storage/action_repo.py`：

```python
import json
import sqlite3
from datetime import datetime


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def replace(conn: sqlite3.Connection, meeting_id: int, actions: list[dict]) -> None:
    ts = now_str()
    conn.execute("DELETE FROM action_item WHERE meeting_id=?", (meeting_id,))
    for a in actions:
        conn.execute(
            "INSERT INTO action_item (meeting_id, owner, task, due, quote,"
            " segment_ids, status, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,'open',?,?)",
            (meeting_id, a.get("owner", ""), a["task"], a.get("due", ""),
             a["quote"], json.dumps(a["segment_ids"], ensure_ascii=False), ts, ts),
        )


def _row(r) -> dict:
    d = dict(r)
    d["segment_ids"] = json.loads(d["segment_ids"])
    return d


def list_for(conn: sqlite3.Connection, meeting_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM action_item WHERE meeting_id=? ORDER BY id", (meeting_id,)
    ).fetchall()
    return [_row(r) for r in rows]


def open_for(conn: sqlite3.Connection, meeting_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM action_item WHERE meeting_id=? AND status='open' ORDER BY id",
        (meeting_id,),
    ).fetchall()
    return [_row(r) for r in rows]
```

`app/storage/relation_repo.py`：

```python
import sqlite3
from datetime import datetime


def replace(conn: sqlite3.Connection, meeting_id: int, relations: list[dict]) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("DELETE FROM relation WHERE meeting_id=?", (meeting_id,))
    for r in relations:
        conn.execute(
            "INSERT INTO relation (meeting_id, target_id, kind, detail, quote, created_at)"
            " VALUES (?,?,?,?,?,?)",
            (meeting_id, r["target_id"], r["kind"], r["detail"], r["quote"], ts),
        )


def list_for(conn: sqlite3.Connection, meeting_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT r.*, m.title AS target_title, m.uid AS target_uid,"
        " m.recorded_at AS target_time"
        " FROM relation r JOIN meeting m ON m.id=r.target_id"
        " WHERE r.meeting_id=? ORDER BY r.id",
        (meeting_id,),
    ).fetchall()
    return [dict(r) for r in rows]
```

- [ ] **Step 4: 运行测试确认通过**

```powershell
python -m pytest tests/unit/test_repos_relation.py -v
```

预期：3 passed。

- [ ] **Step 5: 提交**

```powershell
git add app/storage/action_repo.py app/storage/relation_repo.py tests/unit/test_repos_relation.py
git commit -m "feat: 待办与关联仓储"
```

---

### Task 7: 文件原子落盘与磁盘水位

**Files:**
- Create: `app/storage/files.py`
- Test: `tests/unit/test_files.py`

- [ ] **Step 1: 写失败的测试**

`tests/unit/test_files.py`：

```python
import io

import pytest

from app.storage import files


def test_sanitize_title():
    assert files.sanitize_title('  三季/度:进度会?  ') == "三季-度-进度会-"
    assert files.sanitize_title("") == "未命名会议"
    assert len(files.sanitize_title("长" * 200)) == 80


def test_save_stream_writes_complete_file_and_meta(cfg):
    data = b"fake-audio-bytes"
    path, size, digest = files.save_stream(
        io.BytesIO(data), cfg.inbox_dir, "20261121-100000-abcd",
        "测试会", ".m4a", {"project": "项目A"},
    )
    assert path.name == "20261121-100000-abcd__测试会.m4a"
    assert path.read_bytes() == data
    assert size == len(data)
    assert len(digest) == 64
    assert not list(cfg.inbox_dir.glob("*.part"))
    meta = cfg.inbox_dir / "20261121-100000-abcd__测试会.json"
    assert '"项目A"' in meta.read_text(encoding="utf-8")


def test_save_stream_rejects_oversize(cfg):
    with pytest.raises(ValueError):
        files.save_stream(
            io.BytesIO(b"x" * 100), cfg.inbox_dir, "u", "t", ".m4a",
            {"project": "项目A"}, max_bytes=10,
        )
    assert not list(cfg.inbox_dir.iterdir())


def test_split_stem():
    assert files.split_stem("20261121-100000-abcd__测试会") == (
        "20261121-100000-abcd", "测试会")
    assert files.split_stem("plain") == ("plain", "plain")


def test_move_to_ready(cfg):
    src = cfg.inbox_dir / "a.m4a"
    src.write_bytes(b"x")
    dest = files.move_to_ready(src, cfg.ready_dir)
    assert dest.exists() and not src.exists()
```

- [ ] **Step 2: 运行测试确认失败**

```powershell
python -m pytest tests/unit/test_files.py -v
```

预期：`ModuleNotFoundError: No module named 'app.storage.files'`。

- [ ] **Step 3: 实现文件工具**

`app/storage/files.py`：

```python
"""采集文件的原子性保证：先写 .part，写完 fsync，最后 rename。"""

import hashlib
import json
import os
import re
import shutil
import uuid
from datetime import datetime
from pathlib import Path

AUDIO_SUFFIXES = {".m4a", ".mp3", ".wav", ".opus", ".aac", ".amr", ".flac"}


def sanitize_title(raw: str, fallback: str = "未命名会议") -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\r\n\t]', "-", raw or "").strip(" .")
    return (cleaned or fallback)[:80]


def new_uid(now: datetime | None = None) -> str:
    moment = now or datetime.now()
    return moment.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]


def free_gb(path: Path) -> float:
    return shutil.disk_usage(str(path)).free / (1024 ** 3)


def save_stream(src, inbox: Path, uid: str, title: str, ext: str,
                meta: dict, max_bytes: int | None = None):
    """从文件对象读入，返回 (最终路径, 字节数, sha256)。失败时清理残片。"""
    stem = f"{uid}__{title}"
    part = inbox / f"{stem}{ext}.part"
    meta_path = inbox / f"{stem}.json"
    digest = hashlib.sha256()
    total = 0
    try:
        with part.open("wb") as out:
            while True:
                chunk = src.read(1 << 20)
                if not chunk:
                    break
                total += len(chunk)
                if max_bytes is not None and total > max_bytes:
                    raise ValueError("文件超过大小限制")
                digest.update(chunk)
                out.write(chunk)
            out.flush()
            os.fsync(out.fileno())
        meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        final = inbox / f"{stem}{ext}"
        part.rename(final)
        return final, total, digest.hexdigest()
    except Exception:
        part.unlink(missing_ok=True)
        meta_path.unlink(missing_ok=True)
        raise


def split_stem(stem: str) -> tuple[str, str]:
    if "__" in stem:
        uid, title = stem.split("__", 1)
        return uid, title
    return stem, stem


def move_to_ready(path: Path, ready_dir: Path) -> Path:
    dest = ready_dir / path.name
    shutil.move(str(path), str(dest))
    return dest
```

- [ ] **Step 4: 运行测试确认通过**

```powershell
python -m pytest tests/unit/test_files.py -v
```

预期：5 passed。

- [ ] **Step 5: 提交**

```powershell
git add app/storage/files.py tests/unit/test_files.py
git commit -m "feat: 音频原子落盘与文件工具"
```

---

### Task 8: 登录令牌与限流

**Files:**
- Create: `app/api/__init__.py`（空）、`app/api/errors.py`、`app/api/auth.py`
- Test: `tests/unit/test_auth.py`

- [ ] **Step 1: 写失败的测试**

`tests/unit/test_auth.py`：

```python
from app.api import auth


def test_token_roundtrip_and_expiry():
    token = auth.make_token("secret", expires_ts=1000)
    assert auth.verify_token("secret", token, now_ts=999)
    assert not auth.verify_token("secret", token, now_ts=1000)


def test_token_rejects_tamper():
    token = auth.make_token("secret", expires_ts=1000)
    assert not auth.verify_token("other", token, now_ts=1)
    assert not auth.verify_token("secret", token + "x", now_ts=1)
    assert not auth.verify_token("secret", "bad", now_ts=1)


def test_limiter_blocks_after_five_attempts():
    limiter = auth.LoginLimiter(max_attempts=5, window_sec=60)
    for _ in range(5):
        assert limiter.allow("1.1.1.1", now=100)
    assert not limiter.allow("1.1.1.1", now=101)
    assert limiter.allow("2.2.2.2", now=101)
    assert limiter.allow("1.1.1.1", now=200)
```

- [ ] **Step 2: 运行测试确认失败**

```powershell
python -m pytest tests/unit/test_auth.py -v
```

预期：`ModuleNotFoundError: No module named 'app.api'`。

- [ ] **Step 3: 实现令牌、限流、错误类型与登录路由**

`app/api/__init__.py` 为空文件。`app/api/errors.py`：

```python
from fastapi import Request
from fastapi.responses import JSONResponse


class ApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(
        {"error": {"code": exc.code, "message": exc.message}},
        status_code=exc.status_code,
    )
```

`app/api/auth.py`：

```python
import hashlib
import hmac
import time
from collections import defaultdict, deque

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

router = APIRouter()
COOKIE_NAME = "mm_session"
SESSION_SECONDS = 7 * 86400


def make_token(secret: str, expires_ts: int) -> str:
    payload = str(expires_ts)
    sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def verify_token(secret: str, token: str | None, now_ts: int | None = None) -> bool:
    if not token or "." not in token:
        return False
    payload, sig = token.split(".", 1)
    expected = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return False
    try:
        expires = int(payload)
    except ValueError:
        return False
    return expires > (int(time.time()) if now_ts is None else now_ts)


class LoginLimiter:
    def __init__(self, max_attempts: int = 5, window_sec: int = 60):
        self.max_attempts = max_attempts
        self.window_sec = window_sec
        self._hits: dict[str, deque] = defaultdict(deque)

    def allow(self, ip: str, now: float | None = None) -> bool:
        moment = time.time() if now is None else now
        hits = self._hits[ip]
        while hits and hits[0] <= moment - self.window_sec:
            hits.popleft()
        if len(hits) >= self.max_attempts:
            return False
        hits.append(moment)
        return True


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    from app.web import render
    return render.render("login.html", error=None, standalone=True)


@router.post("/login")
def login_submit(request: Request, password: str = Form("")):
    cfg = request.app.state.cfg
    ip = request.client.host if request.client else "unknown"
    if not request.app.state.limiter.allow(ip):
        from app.api.errors import ApiError
        raise ApiError(429, "rate_limited", "登录尝试过于频繁，请稍后再试")
    if password != cfg.app_password:
        from app.web import render
        return HTMLResponse(
            render.render("login.html", error="口令不正确", standalone=True),
            status_code=401,
        )
    token = make_token(cfg.cookie_secret, int(time.time()) + SESSION_SECONDS)
    resp = RedirectResponse("/", status_code=302)
    resp.set_cookie(COOKIE_NAME, token, httponly=True,
                    samesite="lax", max_age=SESSION_SECONDS)
    return resp


@router.post("/logout")
def logout():
    resp = RedirectResponse("/login", status_code=302)
    resp.delete_cookie(COOKIE_NAME)
    return resp
```

- [ ] **Step 4: 运行测试确认通过**

```powershell
python -m pytest tests/unit/test_auth.py -v
```

预期：3 passed。

- [ ] **Step 5: 提交**

```powershell
git add app/api tests/unit/test_auth.py
git commit -m "feat: 登录令牌、限流与错误响应"
```

---

### Task 9: 应用装配、登录页与健康检查

**Files:**
- Create: `app/web/__init__.py`（空）、`app/web/render.py`、`app/web/pages.py`、`app/web/templates/_style.html`、`base.html`、`login.html`、`index.html`、`app/core/logging.py`、`app/main.py`
- Test: `tests/integration/test_app_boot.py`

- [ ] **Step 1: 写失败的测试**

`tests/integration/test_app_boot.py`：

```python
from fastapi.testclient import TestClient

from app.main import create_app


def test_healthz_needs_no_login(cfg):
    app = create_app(cfg, start_threads=False)
    with TestClient(app) as client:
        assert client.get("/healthz").json() == {"ok": True}


def test_root_redirects_to_login(cfg):
    app = create_app(cfg, start_threads=False)
    with TestClient(app) as client:
        resp = client.get("/", follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["location"] == "/login"


def test_api_returns_401_json(cfg):
    app = create_app(cfg, start_threads=False)
    with TestClient(app) as client:
        resp = client.get("/api/meetings")
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "unauthorized"


def test_login_success_and_logout(cfg):
    app = create_app(cfg, start_threads=False)
    with TestClient(app) as client:
        bad = client.post("/login", data={"password": "wrong"})
        assert bad.status_code == 401
        ok = client.post("/login", data={"password": "test-pass"}, follow_redirects=False)
        assert ok.status_code == 302
        assert client.get("/").status_code == 200
        client.post("/logout", follow_redirects=False)
        assert client.get("/api/meetings").status_code == 401


def test_login_rate_limited(cfg):
    app = create_app(cfg, start_threads=False)
    with TestClient(app) as client:
        codes = [client.post("/login", data={"password": "x"}).status_code
                 for _ in range(6)]
        assert codes[-1] == 429


def test_logging_writes_json_line(cfg):
    from app.core.logging import log_event, setup_logging
    setup_logging(cfg.log_dir)
    log_event("info", "test_event", uid="u1")
    text = (cfg.log_dir / "app.log").read_text(encoding="utf-8")
    assert "test_event" in text
    assert "u1" in text
```

- [ ] **Step 2: 运行测试确认失败**

```powershell
python -m pytest tests/integration/test_app_boot.py -v
```

预期：`ModuleNotFoundError: No module named 'app.main'`。

- [ ] **Step 3: 实现渲染、页面路由与主应用**

`app/web/render.py`：

```python
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

TEMPLATE_DIR = Path(__file__).parent / "templates"

env = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=select_autoescape(["html"]),
)


def mmss(seconds) -> str:
    try:
        total = int(float(seconds))
    except (TypeError, ValueError):
        return "00:00"
    return f"{total // 60:02d}:{total % 60:02d}"


env.filters["mmss"] = mmss


def render(name: str, **context) -> str:
    return env.get_template(name).render(**context)
```

`app/core/logging.py`：

```python
"""JSON Lines 日志，按 10MB × 5 轮转。"""

import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps({
            "ts": self.formatTime(record, "%Y-%m-%d %H:%M:%S"),
            "level": record.levelname,
            "message": record.getMessage(),
        }, ensure_ascii=False)


def setup_logging(log_dir: Path) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("mm")
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    logger.setLevel(logging.INFO)
    file_handler = RotatingFileHandler(
        log_dir / "app.log", maxBytes=10 * 1024 * 1024,
        backupCount=5, encoding="utf-8")
    file_handler.setFormatter(JsonFormatter())
    logger.addHandler(file_handler)
    console = logging.StreamHandler()
    console.setFormatter(JsonFormatter())
    logger.addHandler(console)


def log_event(level: str, event: str, **fields) -> None:
    payload = json.dumps({"event": event, **fields}, ensure_ascii=False)
    logging.getLogger("mm").log(
        getattr(logging, level.upper(), logging.INFO), payload)
```

`app/web/pages.py`（首页在 Task 12 接入真实数据）：

```python
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.web import render

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def home(request: Request):
    return HTMLResponse(render.render("index.html", meetings=[]))
```

`app/web/templates/_style.html`：

```html
<style>
  :root { color-scheme: light; }
  * { box-sizing: border-box; }
  body { margin: 0; background: #f4f5f7; color: #1f2329;
         font: 15px/1.6 "Microsoft YaHei", "PingFang SC", sans-serif; }
  a { color: #1f6feb; text-decoration: none; }
  .wrap { max-width: 1080px; margin: 0 auto; padding: 24px 20px 60px; }
  .topbar { background: #fff; border-bottom: 1px solid #e5e6eb; }
  .topbar .wrap { display: flex; align-items: center; justify-content: space-between;
                  padding: 14px 20px; }
  .brand { font-weight: 700; font-size: 17px; color: #1f2329; }
  .card { background: #fff; border: 1px solid #e5e6eb; border-radius: 10px; padding: 20px; }
  .muted { color: #86909c; font-size: 13px; }
  .btn { display: inline-block; padding: 8px 16px; border-radius: 6px;
         background: #1f6feb; color: #fff; border: 0; cursor: pointer; font-size: 14px; }
  .btn:disabled { opacity: .5; cursor: not-allowed; }
  .btn.ghost { background: #fff; color: #1f2329; border: 1px solid #d0d3d9; }
  .field { margin-bottom: 14px; }
  .field label { display: block; font-size: 13px; margin-bottom: 6px; }
  .field input { width: 100%; padding: 9px 11px; border: 1px solid #d0d3d9;
                 border-radius: 6px; font-size: 14px; }
  .error { color: #d93026; font-size: 13px; margin-bottom: 12px; }
  .chip { display: inline-block; padding: 2px 8px; border-radius: 999px;
          background: #eef1f6; color: #4e5969; font-size: 12px; }
  .chip.done { background: #e8f7ee; color: #1a7f37; }
  .chip.failed { background: #fdeceb; color: #d93026; }
  .chip.processing { background: #eaf2ff; color: #1f6feb; }
</style>
```

`app/web/templates/base.html`：

```html
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{% block title %}会议记忆{% endblock %}</title>
  {% include "_style.html" %}
</head>
<body>
{% if not standalone %}
<div class="topbar">
  <div class="wrap">
    <a class="brand" href="/">会议记忆</a>
    <div>
      <a href="/">会议列表</a>
      <form method="post" action="/logout" style="display:inline;margin-left:16px">
        <button class="btn ghost" type="submit">退出</button>
      </form>
    </div>
  </div>
</div>
{% endif %}
<div class="wrap">{% block content %}{% endblock %}</div>
</body>
</html>
```

`app/web/templates/login.html`：

```html
{% extends "base.html" %}
{% block title %}登录 · 会议记忆{% endblock %}
{% block content %}
<div class="card" style="max-width:380px;margin:80px auto">
  <h2 style="margin-top:0">会议记忆</h2>
  <p class="muted">录音自动转写 · 结构化纪要 · 跨会议关联</p>
  {% if error %}<div class="error">{{ error }}</div>{% endif %}
  <form method="post" action="/login">
    <div class="field">
      <label for="password">访问口令</label>
      <input id="password" name="password" type="password" autofocus required>
    </div>
    <button class="btn" type="submit">进入</button>
  </form>
  <p class="muted" style="margin-bottom:0">使用前请确认已告知参会人录音用途。</p>
</div>
{% endblock %}
```

`app/web/templates/index.html`（Task 12 会替换为带筛选与轮询的版本）：

```html
{% extends "base.html" %}
{% block title %}会议列表 · 会议记忆{% endblock %}
{% block content %}
<div class="card">
  <h1 style="margin-top:0">会议列表</h1>
  <p class="muted">暂无会议。</p>
</div>
{% endblock %}
```

`app/main.py`：

```python
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse

from app.api import auth
from app.api.auth import COOKIE_NAME, verify_token
from app.api.errors import ApiError, api_error_handler
from app.config import Config
from app.storage import db
from app.web import pages


def create_app(cfg: Config | None = None, start_threads: bool = True) -> FastAPI:
    cfg = cfg or Config.from_env()
    problems = cfg.validate()
    if problems:
        raise RuntimeError("配置错误：" + "；".join(problems))
    cfg.ensure_dirs()
    from app.core.logging import setup_logging
    setup_logging(cfg.log_dir)
    db.init_db(cfg.db_path)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        stop = threading.Event()
        app.state.stop_event = stop
        threads = []
        if start_threads:
            from app.pipeline import harvester, maintainer, worker
            threads = [
                harvester.start(cfg, stop),
                worker.start(cfg, stop),
                maintainer.start(cfg, stop),
            ]
        yield
        stop.set()
        for t in threads:
            t.join(timeout=3)

    app = FastAPI(title="会议记忆", lifespan=lifespan)
    app.state.cfg = cfg
    app.state.limiter = auth.LoginLimiter()
    app.add_exception_handler(ApiError, api_error_handler)

    @app.middleware("http")
    async def auth_guard(request: Request, call_next):
        path = request.url.path
        if path in {"/login", "/healthz"} or path.startswith("/static/"):
            return await call_next(request)
        token = request.cookies.get(COOKIE_NAME)
        if verify_token(cfg.cookie_secret, token):
            return await call_next(request)
        if path.startswith("/api/"):
            return JSONResponse(
                {"error": {"code": "unauthorized", "message": "未登录"}},
                status_code=401,
            )
        return RedirectResponse("/login", status_code=302)

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    app.include_router(auth.router)
    app.include_router(pages.router)
    return app


# 启动方式（单进程）：
# python -m uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000
```

- [ ] **Step 4: 运行测试确认通过**

```powershell
python -m pytest tests/integration/test_app_boot.py -v
```

预期：6 passed。若 `python-multipart` 未安装，`Form` 会报错，先执行 `python -m pip install python-multipart`。

- [ ] **Step 5: 提交**

```powershell
git add app/main.py app/web tests/integration/test_app_boot.py
git commit -m "feat: 应用装配、登录页与鉴权中间件"
```

# M1 采集与列表

### Task 10: 上传接口与项目接口

**Files:**
- Create: `app/api/upload.py`、`app/api/projects.py`
- Modify: `app/main.py`（注册两个路由）
- Test: `tests/integration/test_upload_api.py`

- [ ] **Step 1: 写失败的测试**

`tests/integration/test_upload_api.py`：

```python
from fastapi.testclient import TestClient

from app.main import create_app
from app.storage import db, meeting_repo


def _client(cfg):
    app = create_app(cfg, start_threads=False)
    client = TestClient(app)
    client.__enter__()
    client.post("/login", data={"password": "test-pass"})
    return client


def test_upload_creates_uploading_meeting(cfg):
    client = _client(cfg)
    try:
        resp = client.post(
            "/api/meetings",
            files={"file": ("a.m4a", b"fake-bytes", "audio/mp4")},
            data={"title": "测试会", "project_name": "项目A"},
        )
        assert resp.status_code == 200
        uid = resp.json()["uid"]
        conn = db.connect(cfg.db_path)
        try:
            m = meeting_repo.get_by_uid(conn, uid)
        finally:
            conn.close()
        assert m["status"] == "uploading"
        assert m["title"] == "测试会"
        assert (cfg.inbox_dir / m["audio_filename"]).exists()
        assert not list(cfg.inbox_dir.glob("*.part"))
    finally:
        client.__exit__(None, None, None)


def test_upload_rejects_bad_suffix_and_missing_project(cfg):
    client = _client(cfg)
    try:
        bad = client.post("/api/meetings",
                          files={"file": ("a.txt", b"x", "text/plain")},
                          data={"project_name": "项目A"})
        assert bad.status_code == 400
        no_project = client.post("/api/meetings",
                                 files={"file": ("a.m4a", b"x", "audio/mp4")})
        assert no_project.status_code == 400
        assert no_project.json()["error"]["code"] == "upload_invalid"
    finally:
        client.__exit__(None, None, None)


def test_projects_endpoint(cfg):
    client = _client(cfg)
    try:
        resp = client.get("/api/projects")
        names = [p["name"] for p in resp.json()["items"]]
        assert "未归类" in names
    finally:
        client.__exit__(None, None, None)
```

- [ ] **Step 2: 运行测试确认失败**

```powershell
python -m pytest tests/integration/test_upload_api.py -v
```

预期：上传返回 404 或 405。

- [ ] **Step 3: 实现上传与项目接口**

`app/api/upload.py`：

```python
from pathlib import Path

from fastapi import APIRouter, File, Form, Request, UploadFile

from app.api.errors import ApiError
from app.storage import db, files, meeting_repo, project_repo

router = APIRouter(prefix="/api")
TEMPLATE_KEYS = {"standard", "discussion", "report"}


@router.post("/meetings")
async def upload(
    request: Request,
    file: UploadFile = File(...),
    title: str = Form(""),
    project_name: str = Form(""),
    template_key: str = Form("standard"),
):
    cfg = request.app.state.cfg
    ext = Path(file.filename or "").suffix.lower()
    if ext not in files.AUDIO_SUFFIXES:
        raise ApiError(400, "upload_invalid", "不支持的音频格式")
    project_name = project_name.strip()
    if not project_name:
        raise ApiError(400, "upload_invalid", "必须选择项目")
    if template_key not in TEMPLATE_KEYS:
        raise ApiError(400, "upload_invalid", "未知的纪要模板")
    if files.free_gb(cfg.data_dir) < cfg.min_free_gb:
        raise ApiError(503, "storage_full", "服务器磁盘空间不足")

    safe_title = files.sanitize_title(title or Path(file.filename or "").stem)
    uid = files.new_uid()
    meta = {"project": project_name, "title": safe_title,
            "recorded_at": meeting_repo.now_str()}
    try:
        path, size, _ = files.save_stream(
            file.file, cfg.inbox_dir, uid, safe_title, ext, meta,
            max_bytes=cfg.max_upload_mb * 1024 * 1024,
        )
    except ValueError as exc:
        raise ApiError(413, "too_large", str(exc)) from exc

    conn = db.connect(cfg.db_path)
    try:
        pid = project_repo.ensure_project(conn, project_name)
        meeting_repo.create(
            conn, uid=uid, title=safe_title, project_id=pid,
            recorded_at=meta["recorded_at"], audio_filename=path.name,
            audio_size=size, template_key=template_key, status="uploading",
        )
    finally:
        conn.close()
    return {"uid": uid}
```

`app/api/projects.py`：

```python
from fastapi import APIRouter, Request

from app.storage import db, project_repo

router = APIRouter(prefix="/api")


@router.get("/projects")
def list_projects(request: Request):
    conn = db.connect(request.app.state.cfg.db_path)
    try:
        return {"items": project_repo.list_all(conn)}
    finally:
        conn.close()
```

修改 `app/main.py`：导入并注册路由。

```python
from app.api import auth, projects, upload
```

```python
    app.include_router(auth.router)
    app.include_router(upload.router)
    app.include_router(projects.router)
    app.include_router(pages.router)
```

- [ ] **Step 4: 运行测试确认通过**

```powershell
python -m pytest tests/integration/test_upload_api.py -v
```

预期：3 passed。

- [ ] **Step 5: 提交**

```powershell
git add app/api/upload.py app/api/projects.py app/main.py tests/integration/test_upload_api.py
git commit -m "feat: 网页上传接口与项目列表"
```

---

### Task 11: Harvester（inbox → ready）

**Files:**
- Create: `app/pipeline/__init__.py`（空）、`app/pipeline/harvester.py`
- Test: `tests/integration/test_harvester.py`

- [ ] **Step 1: 写失败的测试**

`tests/integration/test_harvester.py`：

```python
from app.pipeline.harvester import harvest_once
from app.storage import db, meeting_repo, project_repo


def test_part_file_is_never_harvested(cfg):
    (cfg.inbox_dir / "u1__会议.m4a.part").write_bytes(b"half")
    assert harvest_once(cfg) == 0
    conn = db.connect(cfg.db_path)
    try:
        assert conn.execute("SELECT COUNT(*) AS n FROM meeting").fetchone()["n"] == 0
    finally:
        conn.close()


def test_complete_file_creates_pending_meeting(cfg):
    (cfg.inbox_dir / "u1__会议.m4a").write_bytes(b"audio")
    (cfg.inbox_dir / "u1__会议.json").write_text(
        '{"project": "项目A", "recorded_at": "2026-11-21 09:00:00"}',
        encoding="utf-8")
    assert harvest_once(cfg) == 1
    conn = db.connect(cfg.db_path)
    try:
        m = meeting_repo.get_by_uid(conn, "u1")
        pid = project_repo.ensure_project(conn, "项目A")
        assert m["status"] == "pending"
        assert m["project_id"] == pid
        assert m["recorded_at"] == "2026-11-21 09:00:00"
        assert (cfg.ready_dir / m["audio_filename"]).exists()
        assert not (cfg.inbox_dir / "u1__会议.json").exists()
    finally:
        conn.close()


def test_uploading_record_is_promoted(cfg):
    conn = db.connect(cfg.db_path)
    try:
        pid = project_repo.ensure_project(conn, "项目A")
        mid = meeting_repo.create(
            conn, uid="u2", title="网页会议", project_id=pid,
            recorded_at="2026-11-21 10:00:00",
            audio_filename="u2__网页会议.m4a", status="uploading")
    finally:
        conn.close()
    (cfg.inbox_dir / "u2__网页会议.m4a").write_bytes(b"audio")
    assert harvest_once(cfg) == 1
    conn = db.connect(cfg.db_path)
    try:
        m = meeting_repo.get_by_uid(conn, "u2")
        assert m["status"] == "pending"
        assert (cfg.ready_dir / m["audio_filename"]).exists()
    finally:
        conn.close()
```

- [ ] **Step 2: 运行测试确认失败**

```powershell
python -m pytest tests/integration/test_harvester.py -v
```

预期：`ModuleNotFoundError: No module named 'app.pipeline'`。

- [ ] **Step 3: 实现 Harvester**

`app/pipeline/harvester.py`：

```python
"""扫描 inbox，只接收完整文件；.part 一律跳过。"""

import json
import threading
import traceback
from datetime import datetime
from pathlib import Path

from app.config import Config
from app.storage import db, files, meeting_repo, project_repo


def _read_meta(path: Path, fallback_title: str) -> dict:
    meta_path = path.with_suffix(".json")
    data: dict = {}
    if meta_path.exists():
        try:
            data = json.loads(meta_path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            data = {}
        meta_path.unlink(missing_ok=True)
    mtime = datetime.fromtimestamp(path.stat().st_mtime)
    return {
        "project": (data.get("project") or "未归类").strip() or "未归类",
        "title": (data.get("title") or fallback_title).strip() or fallback_title,
        "recorded_at": data.get("recorded_at")
        or mtime.strftime("%Y-%m-%d %H:%M:%S"),
    }


def harvest_once(cfg: Config) -> int:
    conn = db.connect(cfg.db_path)
    moved = 0
    try:
        for path in sorted(cfg.inbox_dir.iterdir()):
            if not path.is_file():
                continue
            if path.suffix.lower() not in files.AUDIO_SUFFIXES:
                continue  # .part 与旁挂 JSON 都在这里被忽略
            uid, title = files.split_stem(path.stem)
            meta = _read_meta(path, title)
            dest = files.move_to_ready(path, cfg.ready_dir)
            row = meeting_repo.get_by_uid(conn, uid)
            if row is None:
                pid = project_repo.ensure_project(conn, meta["project"])
                meeting_repo.create(
                    conn, uid=uid, title=meta["title"], project_id=pid,
                    recorded_at=meta["recorded_at"], audio_filename=dest.name,
                    audio_size=dest.stat().st_size, status="pending",
                )
            else:
                fields = {"audio_filename": dest.name,
                          "audio_size": dest.stat().st_size}
                if row["status"] == "uploading":
                    fields["status"] = "pending"
                meeting_repo.update_fields(conn, row["id"], **fields)
            moved += 1
    finally:
        conn.close()
    return moved


def start(cfg: Config, stop: threading.Event) -> threading.Thread:
    def loop() -> None:
        while not stop.is_set():
            try:
                harvest_once(cfg)
            except Exception:
                traceback.print_exc()
            stop.wait(cfg.scan_interval)

    thread = threading.Thread(target=loop, daemon=True, name="harvester")
    thread.start()
    return thread
```

- [ ] **Step 4: 运行测试确认通过**

```powershell
python -m pytest tests/integration/test_harvester.py -v
```

预期：3 passed。

- [ ] **Step 5: 提交**

```powershell
git add app/pipeline tests/integration/test_harvester.py
git commit -m "feat: inbox 目录监听与入库"
```

---

### Task 12: 列表页、状态接口与上传交互

**Files:**
- Create: `app/api/meetings.py`
- Replace: `app/web/templates/index.html`
- Modify: `app/web/pages.py`、`app/main.py`
- Test: `tests/integration/test_list_page.py`

- [ ] **Step 1: 写失败的测试**

`tests/integration/test_list_page.py`：

```python
from fastapi.testclient import TestClient

from app.main import create_app
from app.storage import db, meeting_repo, project_repo


def _seed(cfg):
    conn = db.connect(cfg.db_path)
    try:
        pid = project_repo.ensure_project(conn, "项目A")
        meeting_repo.create(
            conn, uid="20261121-100000-abcd", title="三季度进度会",
            project_id=pid, recorded_at="2026-11-21 10:00:00",
            audio_filename="a.m4a", status="pending")
    finally:
        conn.close()


def _client(cfg):
    client = TestClient(create_app(cfg, start_threads=False))
    client.__enter__()
    client.post("/login", data={"password": "test-pass"})
    return client


def test_index_lists_meeting(cfg):
    _seed(cfg)
    client = _client(cfg)
    try:
        html = client.get("/").text
        assert "三季度进度会" in html
        assert "项目A" in html
        assert "排队中" in html
    finally:
        client.__exit__(None, None, None)


def test_status_endpoint(cfg):
    _seed(cfg)
    client = _client(cfg)
    try:
        data = client.get("/api/meetings/20261121-100000-abcd/status").json()
        assert data["status"] == "pending"
        assert data["status_label"] == "排队中"
        assert data["can_retry"] is False
    finally:
        client.__exit__(None, None, None)


def test_list_api_filters_by_project(cfg):
    _seed(cfg)
    client = _client(cfg)
    try:
        projects = client.get("/api/projects").json()["items"]
        pid = next(p["id"] for p in projects if p["name"] == "项目A")
        data = client.get(f"/api/meetings?project_id={pid}").json()
        assert data["total"] == 1
        assert data["items"][0]["uid"] == "20261121-100000-abcd"
    finally:
        client.__exit__(None, None, None)
```

- [ ] **Step 2: 运行测试确认失败**

```powershell
python -m pytest tests/integration/test_list_page.py -v
```

预期：列表页没有会议标题，状态接口 404。

- [ ] **Step 3: 实现接口与页面**

`app/api/meetings.py`：

```python
from fastapi import APIRouter, Request

from app.api.errors import ApiError
from app.core import state
from app.storage import db, meeting_repo

router = APIRouter(prefix="/api")


@router.get("/meetings")
def list_meetings(request: Request, project_id: int | None = None,
                  status: str | None = None, date: str | None = None,
                  page: int = 1, size: int = 20):
    conn = db.connect(request.app.state.cfg.db_path)
    try:
        items, total = meeting_repo.list_page(
            conn, project_id=project_id, status=status,
            date=date, page=max(page, 1), size=min(max(size, 1), 100))
        return {"items": items, "total": total}
    finally:
        conn.close()


@router.get("/meetings/{uid}/status")
def meeting_status(request: Request, uid: str):
    conn = db.connect(request.app.state.cfg.db_path)
    try:
        m = meeting_repo.get_by_uid(conn, uid)
        if not m:
            raise ApiError(404, "not_found", "会议不存在")
        return {
            "status": m["status"],
            "status_label": state.STATUS_LABELS.get(m["status"], m["status"]),
            "error_code": m["error_code"],
            "error_msg": m["error_msg"],
            "retry_count": m["retry_count"],
            "can_retry": state.can_retry(m),
        }
    finally:
        conn.close()
```

`app/web/pages.py` 整体替换：

```python
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.core import state
from app.storage import db, meeting_repo, project_repo
from app.web import render

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def home(request: Request, project_id: int | None = None,
         status: str | None = None, date: str | None = None, page: int = 1):
    conn = db.connect(request.app.state.cfg.db_path)
    try:
        items, total = meeting_repo.list_page(
            conn, project_id=project_id, status=status,
            date=date, page=max(page, 1))
        projects = project_repo.list_all(conn)
    finally:
        conn.close()
    return HTMLResponse(render.render(
        "index.html", meetings=items, projects=projects, total=total,
        page=page, filters={"project_id": project_id, "status": status, "date": date},
        labels=state.STATUS_LABELS,
    ))
```

`app/web/templates/index.html` 整体替换：

```html
{% extends "base.html" %}
{% block title %}会议列表 · 会议记忆{% endblock %}
{% block content %}
<div class="card" style="margin-bottom:16px">
  <details>
    <summary style="cursor:pointer;font-weight:600">上传会议录音</summary>
    <form id="upload-form" style="margin-top:16px">
      <div class="field">
        <label>音频文件</label>
        <input type="file" name="file" required
               accept=".m4a,.mp3,.wav,.opus,.aac,.amr,.flac">
      </div>
      <div class="field">
        <label>会议标题（缺省取文件名）</label>
        <input name="title" placeholder="例如：三季度进度会">
      </div>
      <div class="field">
        <label>项目</label>
        <select name="project_name" required>
          {% for p in projects %}<option value="{{ p.name }}">{{ p.name }}</option>{% endfor %}
        </select>
        <input name="new_project" placeholder="或输入新项目名（优先于下拉）"
               style="margin-top:8px">
      </div>
      <div class="field">
        <label>纪要模板</label>
        <select name="template_key">
          <option value="standard">常规会议</option>
          <option value="discussion">座谈交流</option>
          <option value="report">工作汇报</option>
        </select>
      </div>
      <progress id="upload-progress" value="0" max="100"
                style="width:100%;display:none"></progress>
      <button class="btn" type="submit">开始上传</button>
      <span id="upload-error" class="error"></span>
    </form>
  </details>
</div>

<form method="get" class="card" style="display:flex;gap:12px;align-items:end;flex-wrap:wrap">
  <div class="field" style="margin:0">
    <label>项目</label>
    <select name="project_id">
      <option value="">全部</option>
      {% for p in projects %}
      <option value="{{ p.id }}" {% if filters.project_id == p.id %}selected{% endif %}>{{ p.name }}</option>
      {% endfor %}
    </select>
  </div>
  <div class="field" style="margin:0">
    <label>状态</label>
    <select name="status">
      <option value="">全部</option>
      {% for key, label in labels.items() %}
      <option value="{{ key }}" {% if filters.status == key %}selected{% endif %}>{{ label }}</option>
      {% endfor %}
    </select>
  </div>
  <div class="field" style="margin:0">
    <label>日期</label>
    <input type="date" name="date" value="{{ filters.date or '' }}">
  </div>
  <button class="btn" type="submit">筛选</button>
</form>

{% for m in meetings %}
<div class="card" style="margin-top:12px" data-status-url="/api/meetings/{{ m.uid }}/status">
  <div style="display:flex;justify-content:space-between;gap:12px;align-items:center">
    <div>
      <a href="/m/{{ m.uid }}"><strong>{{ m.title }}</strong></a>
      <div class="muted">{{ m.project_name }} · {{ m.recorded_at }} · {{ m.duration_sec|mmss }}</div>
    </div>
    <div>
      <span class="chip {% if m.status == 'done' %}done{% elif m.status == 'failed' %}failed{% else %}processing{% endif %}">
        {{ labels.get(m.status, m.status) }}
      </span>
      <span class="muted">待办 {{ m.open_actions }}</span>
    </div>
  </div>
</div>
{% else %}
<div class="card" style="margin-top:12px"><p class="muted">暂无会议。</p></div>
{% endfor %}

<p class="muted" style="margin-top:20px">
  共 {{ total }} 场 · <a href="/site/index.html" target="_blank">静态归档</a>
</p>

<script>
const form = document.getElementById("upload-form");
if (form) {
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const data = new FormData(form);
    const newProject = (data.get("new_project") || "").trim();
    if (newProject) data.set("project_name", newProject);
    const bar = document.getElementById("upload-progress");
    const err = document.getElementById("upload-error");
    bar.style.display = "block";
    err.textContent = "";
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/meetings");
    xhr.upload.onprogress = (e) => { if (e.lengthComputable) bar.value = e.loaded / e.total * 100; };
    xhr.onload = () => {
      if (xhr.status === 200) {
        location.href = "/m/" + JSON.parse(xhr.responseText).uid;
      } else {
        try { err.textContent = JSON.parse(xhr.responseText).error.message; }
        catch (_) { err.textContent = "上传失败"; }
      }
    };
    xhr.onerror = () => { err.textContent = "网络错误"; };
    xhr.send(data);
  });
}

const rows = Array.from(document.querySelectorAll("[data-status-url]"));
const active = rows.filter(r => !r.querySelector(".chip.done") && !r.querySelector(".chip.failed"));
if (active.length) {
  setTimeout(() => location.reload(), 3000);
}
</script>
{% endblock %}
```

修改 `app/main.py`：

```python
from app.api import auth, meetings, projects, upload
```

```python
    app.include_router(auth.router)
    app.include_router(upload.router)
    app.include_router(projects.router)
    app.include_router(meetings.router)
    app.include_router(pages.router)
```

- [ ] **Step 4: 运行测试确认通过**

```powershell
python -m pytest tests/integration/test_list_page.py -v
```

预期：3 passed。

- [ ] **Step 5: 提交**

```powershell
git add app/api/meetings.py app/web/pages.py app/web/templates/index.html app/main.py tests/integration/test_list_page.py
git commit -m "feat: 会议列表、状态接口与上传交互"
```

---

# M2 转写

### Task 13: ASR 接口、mock 与转写阶段

**Files:**
- Create: `app/providers/__init__.py`、`app/providers/errors.py`、`app/providers/base.py`、`app/providers/asr_mock.py`、`app/pipeline/media.py`、`app/pipeline/transcribe.py`
- Test: `tests/unit/test_transcribe.py`

- [ ] **Step 1: 写失败的测试**

`tests/unit/test_transcribe.py`：

```python
from app.pipeline import transcribe
from app.providers import build_asr
from app.providers.errors import ProviderError


def test_mock_asr_segments_are_continuous(cfg):
    provider = build_asr(cfg)
    segments = provider.transcribe(cfg.inbox_dir / "whatever.m4a")
    assert segments
    assert [s["idx"] for s in segments] == list(range(len(segments)))
    assert all(s["speaker"] for s in segments)


def test_transcribe_stage_writes_file_check(cfg, tmp_path):
    audio = cfg.ready_dir / "u1__会.m4a"
    audio.write_bytes(b"x")
    meeting = {"id": 1, "uid": "u1", "audio_filename": audio.name,
               "template_key": "standard"}
    segments = transcribe.run(cfg, meeting)
    assert len(segments) > 3
    assert segments[0]["start"] == 0.0


def test_transcribe_missing_file_raises(cfg):
    meeting = {"id": 1, "uid": "u1", "audio_filename": "missing.m4a",
               "template_key": "standard"}
    try:
        transcribe.run(cfg, meeting)
        assert False, "应当抛出 ProviderError"
    except ProviderError as exc:
        assert exc.code == "file_missing"
```

- [ ] **Step 2: 运行测试确认失败**

```powershell
python -m pytest tests/unit/test_transcribe.py -v
```

预期：`ModuleNotFoundError: No module named 'app.providers'`。

- [ ] **Step 3: 实现 Provider 与转写阶段**

`app/providers/errors.py`：

```python
class ProviderError(Exception):
    def __init__(self, code: str, message: str, transient: bool = False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.transient = transient
```

`app/providers/base.py`：

```python
from pathlib import Path
from typing import Protocol


class AsrProvider(Protocol):
    def transcribe(self, audio_path: Path) -> list[dict]: ...


class LlmProvider(Protocol):
    def complete_json(self, system: str, user: str) -> dict: ...
```

`app/providers/asr_mock.py`：

```python
from pathlib import Path

SCRIPT = [
    ("王总", "今天主要过一下三季度的进度，顺便把年底前要落的几件事定下来。"),
    ("李工", "系统这边三季度的功能都上完了，还有一个数据同步的问题没有解决。"),
    ("王总", "数据同步卡在哪里了？"),
    ("李工", "对方接口不稳定，高峰期会丢数据。"),
    ("张敏", "这个问题我们提过两次了，对方一直没给排期。"),
    ("王总", "这个不能再拖了，决定月底前走一次高层协调，张敏负责对接。"),
    ("张敏", "好的，我下周先把问题清单整理出来。"),
    ("李工", "另外测试环境下周可以交付，需要提前申请资源。"),
    ("王总", "资源的事让运维配合，李工负责提申请。"),
    ("张敏", "座谈这块的预算还没定，要看四季度有没有调整。"),
    ("王总", "预算先待定，回头再看。"),
    ("李工", "还有一个想法，能不能把会议记录自动归档，省得每次翻聊天记录。"),
    ("王总", "这个可以研究一下，先做个原型看看效果。"),
]


class MockAsr:
    def transcribe(self, audio_path: Path) -> list[dict]:
        segments = []
        cursor = 0.0
        for speaker, text in SCRIPT:
            duration = max(3.0, len(text) * 0.28)
            segments.append({
                "idx": len(segments),
                "start": round(cursor, 1),
                "end": round(cursor + duration, 1),
                "speaker": speaker,
                "text": text,
            })
            cursor += duration + 0.8
        return segments
```

`app/providers/__init__.py`：

```python
from app.config import Config
from app.providers.asr_mock import MockAsr


def build_asr(cfg: Config):
    if cfg.asr_backend == "mock":
        return MockAsr()
    from app.providers.asr_funasr import FunAsrProvider
    return FunAsrProvider(cfg)
```

`app/pipeline/media.py`：

```python
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
```

`app/pipeline/transcribe.py`：

```python
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
```

- [ ] **Step 4: 运行测试确认通过**

```powershell
python -m pytest tests/unit/test_transcribe.py -v
```

预期：3 passed。

- [ ] **Step 5: 提交**

```powershell
git add app/providers app/pipeline/media.py app/pipeline/transcribe.py tests/unit/test_transcribe.py
git commit -m "feat: ASR Provider 接口、mock 与转写阶段"
```

---

### Task 14: FunASR 本地转写与说话人分离

**Files:**
- Create: `app/providers/asr_funasr.py`
- Test: `tests/unit/test_asr_funasr.py`

- [ ] **Step 1: 写失败的测试**

`tests/unit/test_asr_funasr.py`：

```python
import sys
import types
from dataclasses import replace

from app.providers.asr_funasr import FunAsrProvider


def _prepare_dirs(cfg):
    for name in ("asr", "vad", "punc", "spk"):
        (cfg.funasr_model_dir / name).mkdir(parents=True, exist_ok=True)


def test_parses_sentence_info_and_speakers(cfg, monkeypatch, tmp_path):
    _prepare_dirs(cfg)
    calls = {}

    class FakeModel:
        def generate(self, **kwargs):
            calls.update(kwargs)
            return [{"sentence_info": [
                {"start": 0, "end": 1500, "spk": 0, "text": "第一句。"},
                {"start": 1500, "end": 3200, "spk": 1, "text": "第二句。"},
            ]}]

    fake_module = types.ModuleType("funasr")
    fake_module.AutoModel = lambda **kwargs: FakeModel()
    monkeypatch.setitem(sys.modules, "funasr", fake_module)

    provider = FunAsrProvider(replace(cfg, asr_backend="funasr"))
    segments = provider.transcribe(tmp_path / "a.wav")

    assert [s["speaker"] for s in segments] == ["说话人1", "说话人2"]
    assert segments[1]["start"] == 1.5
    assert segments[1]["end"] == 3.2
    assert calls["input"].endswith("a.wav")
```

- [ ] **Step 2: 运行测试确认失败**

```powershell
python -m pytest tests/unit/test_asr_funasr.py -v
```

预期：`ModuleNotFoundError: No module named 'app.providers.asr_funasr'`。

- [ ] **Step 3: 实现 FunASR Provider**

`app/providers/asr_funasr.py`：

```python
"""本地 FunASR：paraformer-zh + fsmn-vad + ct-punc + cam++。

模型目录约定：
    {FUNASR_MODEL_DIR}/asr    paraformer-zh
    {FUNASR_MODEL_DIR}/vad    fsmn-vad
    {FUNASR_MODEL_DIR}/punc   ct-punc
    {FUNASR_MODEL_DIR}/spk    cam++
"""

from pathlib import Path

from app.config import Config
from app.providers.errors import ProviderError


class FunAsrProvider:
    def __init__(self, cfg: Config):
        self.model_dir = cfg.funasr_model_dir
        self.device = cfg.funasr_device
        self.hotword_file = cfg.hotword_file
        self._model = None

    def _load(self):
        if self._model is not None:
            return self._model
        try:
            from funasr import AutoModel
        except ImportError as exc:
            raise ProviderError(
                "asr_unavailable",
                "未安装 funasr，请执行 python -m pip install -r requirements-asr.txt",
            ) from exc
        dirs = {name: self.model_dir / name
                for name in ("asr", "vad", "punc", "spk")}
        for label, path in dirs.items():
            if not path.exists():
                raise ProviderError("asr_unavailable", f"模型目录缺失：{path}")
        self._model = AutoModel(
            model=str(dirs["asr"]),
            vad_model=str(dirs["vad"]),
            punc_model=str(dirs["punc"]),
            spk_model=str(dirs["spk"]),
            device=self.device,
            disable_update=True,
        )
        return self._model

    def _hotwords(self) -> str | None:
        if not self.hotword_file.exists():
            return None
        words = [w.strip() for w in
                 self.hotword_file.read_text(encoding="utf-8").splitlines()
                 if w.strip()]
        return " ".join(words) or None

    def transcribe(self, audio_path: Path) -> list[dict]:
        model = self._load()
        try:
            result = model.generate(
                input=str(audio_path),
                hotword=self._hotwords(),
                sentence_timestamp=True,
            )
        except Exception as exc:
            raise ProviderError("asr_unavailable",
                                f"FunASR 识别失败：{exc}", transient=True) from exc
        if not result:
            return []

        item = result[0]
        segments: list[dict] = []
        for sentence in item.get("sentence_info") or []:
            text = (sentence.get("text") or "").strip()
            if not text:
                continue
            speaker = int(sentence.get("spk", 0)) + 1
            segments.append({
                "idx": len(segments),
                "start": round(float(sentence.get("start", 0)) / 1000.0, 2),
                "end": round(float(sentence.get("end", 0)) / 1000.0, 2),
                "speaker": f"说话人{speaker}",
                "text": text,
            })
        if not segments:
            text = (item.get("text") or "").strip()
            if text:
                segments.append({"idx": 0, "start": 0.0, "end": 0.0,
                                 "speaker": "说话人1", "text": text})
        return segments
```

- [ ] **Step 4: 运行测试确认通过**

```powershell
python -m pytest tests/unit/test_asr_funasr.py -v
```

预期：1 passed。

- [ ] **Step 5: 提交**

```powershell
git add app/providers/asr_funasr.py tests/unit/test_asr_funasr.py
git commit -m "feat: 本地 FunASR 转写与说话人分离"
```

---

# M3 纪要

### Task 15: LLM Provider 与纪要生成、校验、分块

**Files:**
- Create: `app/providers/llm_mock.py`、`app/providers/llm_openai.py`、`app/pipeline/minutes.py`
- Modify: `app/providers/__init__.py`（增加 `build_llm`）
- Test: `tests/unit/test_minutes.py`

- [ ] **Step 1: 写失败的测试**

`tests/unit/test_minutes.py`：

```python
import pytest

from app.pipeline import minutes


def _segments():
    return [
        {"idx": 0, "start": 0, "end": 4, "speaker": "王总",
         "text": "今天过一下进度。"},
        {"idx": 1, "start": 4, "end": 8, "speaker": "李工",
         "text": "数据同步还没解决。"},
        {"idx": 2, "start": 8, "end": 12, "speaker": "张敏",
         "text": "我下周把问题清单整理出来。"},
        {"idx": 3, "start": 12, "end": 16, "speaker": "王总",
         "text": "预算待定，回头再看。"},
    ]


def test_validate_rejects_missing_quote():
    data = {
        "summary": "会议。", "topics": [{"title": "进度", "points": [], "segment_ids": [0]}],
        "decisions": [{"text": "决定", "quote": "", "segment_ids": [0]}],
        "actions": [], "open_issues": [], "people": [],
    }
    with pytest.raises(minutes.MinutesValidationError):
        minutes.validate_minutes(data, 4)


def test_validate_rejects_out_of_range_and_normalizes_owner():
    data = {
        "summary": "会议。", "topics": [{"title": "进度", "points": [], "segment_ids": [0]}],
        "decisions": [],
        "actions": [{"owner": "", "task": "整理清单", "due": "",
                     "quote": "我下周把问题清单整理出来", "segment_ids": [2]}],
        "open_issues": [], "people": [],
    }
    result = minutes.validate_minutes(data, 4)
    assert result["actions"][0]["owner"] == "待指定"

    data["actions"][0]["segment_ids"] = [99]
    with pytest.raises(minutes.MinutesValidationError):
        minutes.validate_minutes(data, 4)


def test_generate_with_mock_returns_valid_minutes(cfg):
    result = minutes.generate(cfg, _segments(), "standard")
    assert result["summary"]
    assert result["topics"]
    assert any(a["segment_ids"] == [2] for a in result["actions"])


def test_chunk_segments_covers_all_with_overlap():
    segments = [{"idx": i, "start": i, "end": i + 1, "speaker": "说话人1",
                 "text": "字" * 100} for i in range(50)]
    chunks = minutes.chunk_segments(segments, max_chars=1000, overlap_chars=100)
    assert len(chunks) > 1
    covered = {s["idx"] for chunk in chunks for s in chunk}
    assert covered == {s["idx"] for s in segments}


def test_merge_parts_dedupes():
    part = {"summary": "A", "topics": [{"title": "t", "points": [], "segment_ids": [0]}],
            "decisions": [], "actions": [], "open_issues": [], "people": []}
    merged = minutes.merge_parts([part, part])
    assert len(merged["topics"]) == 1
```

- [ ] **Step 2: 运行测试确认失败**

```powershell
python -m pytest tests/unit/test_minutes.py -v
```

预期：`ModuleNotFoundError: No module named 'app.pipeline.minutes'`。

- [ ] **Step 3: 实现 mock/openai Provider 与纪要流水线**

`app/providers/llm_mock.py`：

```python
import re

LINE = re.compile(r"^\[#(\d+)\] \d{2}:\d{2}:\d{2} (\S+) (.+)$", re.M)
DECISION = ("决定", "定了", "结论", "拍板", "确定")
ACTION = ("负责", "跟进", "下周", "月底", "之前", "提交", "整理", "对接", "配合", "推进")
OPEN = ("待定", "再看看", "没定", "回头", "再说", "看情况")


class MockLlm:
    def complete_json(self, system: str, user: str) -> dict:
        segments = [
            {"idx": int(m.group(1)), "speaker": m.group(2), "text": m.group(3).strip()}
            for m in LINE.finditer(user)
        ]
        if not segments:
            return {"summary": "无有效内容。", "topics": [{"title": "无内容", "points": [], "segment_ids": []}],
                    "decisions": [], "actions": [], "open_issues": [], "people": []}

        topics = []
        for start in range(0, len(segments), 4):
            group = segments[start:start + 4]
            topics.append({
                "title": (group[0]["text"][:14] or "议题") + "…",
                "points": [s["text"] for s in group],
                "segment_ids": [s["idx"] for s in group],
            })

        def hits(keywords):
            return [s for s in segments if any(k in s["text"] for k in keywords)]

        decisions = [{"text": s["text"], "quote": s["text"],
                      "segment_ids": [s["idx"]]} for s in hits(DECISION)]
        actions = [{"owner": "待指定", "task": s["text"], "due": "",
                    "quote": s["text"], "segment_ids": [s["idx"]]}
                   for s in hits(ACTION)]
        open_issues = [{"text": s["text"], "reason": "未形成结论",
                        "segment_ids": [s["idx"]]} for s in hits(OPEN)]
        people = [{"name": name, "role": "参会人"}
                  for name in sorted({s["speaker"] for s in segments})]
        summary = "本次会议共 " + str(len(segments)) + " 段发言，讨论了" + \
                  "、".join(t["title"] for t in topics[:3])
        return {"summary": summary, "topics": topics, "decisions": decisions,
                "actions": actions, "open_issues": open_issues, "people": people}
```

`app/providers/llm_openai.py`：

```python
import json

import httpx

from app.config import Config
from app.providers.errors import ProviderError


class OpenAiLlm:
    def __init__(self, cfg: Config):
        self.base_url = cfg.llm_base_url
        self.api_key = cfg.llm_api_key
        self.model = cfg.llm_model

    def complete_json(self, system: str, user: str) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }
        try:
            response = httpx.post(f"{self.base_url}/chat/completions",
                                  json=payload, headers=headers, timeout=300)
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise ProviderError("llm_unavailable", "大模型请求超时", transient=True) from exc
        except httpx.HTTPError as exc:
            raise ProviderError("llm_unavailable", f"大模型请求失败：{exc}", transient=True) from exc

        content = response.json()["choices"][0]["message"]["content"]
        try:
            return json.loads(content)
        except ValueError as exc:
            raise ProviderError("llm_bad_json", "大模型未返回合法 JSON") from exc
```

修改 `app/providers/__init__.py`，追加：

```python
def build_llm(cfg: Config):
    if cfg.llm_provider == "mock":
        from app.providers.llm_mock import MockLlm
        return MockLlm()
    from app.providers.llm_openai import OpenAiLlm
    return OpenAiLlm(cfg)
```

`app/pipeline/minutes.py`：

```python
"""纪要生成：统一 schema、强制引用、超长文本分块汇总。"""

import json

from app.config import Config
from app.providers import build_llm

REQUIRED_KEYS = ("summary", "topics", "decisions", "actions", "open_issues", "people")
CHUNK_THRESHOLD = 24000
CHUNK_SIZE = 8000
CHUNK_OVERLAP = 300

SYSTEM_PROMPT = """你是会议纪要助手。只依据给定的逐字稿整理，不得补充逐字稿中没有的事实。
输出严格 JSON，顶层字段固定为：
summary(string)、topics(list)、decisions(list)、actions(list)、open_issues(list)、people(list)。
topics 每条：{"title": str, "points": [str], "segment_ids": [int]}。
decisions 每条：{"text": str, "quote": str, "segment_ids": [int]}。
actions 每条：{"owner": str, "task": str, "due": str, "quote": str, "segment_ids": [int]}。
open_issues 每条：{"text": str, "reason": str, "segment_ids": [int]}。
people 每条：{"name": str, "role": str}。
所有 decisions/actions/open_issues 必须给出逐字稿原文 quote 与对应 segment_ids；
无法确定的信息写“待定”或“待指定”，不得编造。只输出 JSON，不要解释。"""

TEMPLATE_HINTS = {
    "standard": "\n模板：常规会议，均衡输出全部字段。",
    "discussion": "\n模板：座谈交流，重点提炼各方观点与 people，弱化决策。",
    "report": "\n模板：工作汇报，重点提炼进展、问题与下一步，弱化决策。",
}


class MinutesValidationError(Exception):
    pass


def _timestamp(seconds) -> str:
    total = int(float(seconds))
    return f"{total // 3600:02d}:{total % 3600 // 60:02d}:{total % 60:02d}"


def build_user_prompt(segments: list[dict]) -> str:
    lines = [f"[#{s['idx']}] {_timestamp(s['start'])} {s['speaker']} {s['text']}"
             for s in segments]
    return "以下是会议逐字稿，请生成纪要：\n" + "\n".join(lines)


def validate_minutes(data: dict, segment_count: int) -> dict:
    if not isinstance(data, dict):
        raise MinutesValidationError("输出不是 JSON 对象")
    summary = data.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise MinutesValidationError("summary 为空")
    topics = data.get("topics")
    if not isinstance(topics, list) or not topics:
        raise MinutesValidationError("topics 为空")
    for key in ("decisions", "actions", "open_issues"):
        items = data.get(key, [])
        if not isinstance(items, list):
            raise MinutesValidationError(f"{key} 不是数组")
        for item in items:
            if not str(item.get("quote") or "").strip():
                raise MinutesValidationError(f"{key} 存在空 quote")
            ids = item.get("segment_ids") or []
            if not ids or not all(isinstance(i, int) and 0 <= i < segment_count for i in ids):
                raise MinutesValidationError(f"{key} 的 segment_ids 非法")
    for action in data.get("actions", []):
        if not str(action.get("task") or "").strip():
            raise MinutesValidationError("actions 存在空 task")
        if not str(action.get("owner") or "").strip():
            action["owner"] = "待指定"
    for decision in data.get("decisions", []):
        if not str(decision.get("text") or "").strip():
            raise MinutesValidationError("decisions 存在空 text")
    data.setdefault("people", [])
    return {key: data[key] for key in REQUIRED_KEYS}


def chunk_segments(segments: list[dict], max_chars: int = CHUNK_SIZE,
                   overlap_chars: int = CHUNK_OVERLAP) -> list[list[dict]]:
    chunks: list[list[dict]] = []
    current: list[dict] = []
    length = 0
    for segment in segments:
        size = len(segment["text"])
        if current and length + size > max_chars:
            chunks.append(current)
            tail: list[dict] = []
            tail_len = 0
            for item in reversed(current):
                tail.insert(0, item)
                tail_len += len(item["text"])
                if tail_len >= overlap_chars:
                    break
            current = tail
            length = tail_len
        current.append(segment)
        length += size
    if current:
        chunks.append(current)
    return chunks


def merge_parts(parts: list[dict]) -> dict:
    merged = {key: [] for key in REQUIRED_KEYS}
    merged["summary"] = ""
    seen: set[str] = set()
    summaries: list[str] = []
    for part in parts:
        if part.get("summary"):
            summaries.append(part["summary"])
        for key in ("topics", "decisions", "actions", "open_issues", "people"):
            for item in part.get(key, []):
                signature = json.dumps(item, ensure_ascii=False, sort_keys=True)
                if signature in seen:
                    continue
                seen.add(signature)
                merged[key].append(item)
    merged["summary"] = "；".join(summaries)[:1000]
    return merged


def _request_valid(provider, segments: list[dict], template_key: str,
                   total_count: int) -> dict:
    user = build_user_prompt(segments) + TEMPLATE_HINTS.get(template_key, "")
    last_error: MinutesValidationError | None = None
    for _ in range(2):
        data = provider.complete_json(SYSTEM_PROMPT, user)
        try:
            return validate_minutes(data, total_count)
        except MinutesValidationError as exc:
            last_error = exc
            user += f"\n\n上次输出不合法：{exc}。请修正后只输出 JSON。"
    raise last_error  # type: ignore[misc]


def generate(cfg: Config, segments: list[dict], template_key: str = "standard") -> dict:
    provider = build_llm(cfg)
    total_chars = sum(len(s["text"]) for s in segments)
    chunks = [segments] if total_chars <= CHUNK_THRESHOLD else chunk_segments(segments)
    parts = [_request_valid(provider, chunk, template_key, len(segments))
             for chunk in chunks]
    data = parts[0] if len(parts) == 1 else merge_parts(parts)
    return validate_minutes(data, len(segments))
```

- [ ] **Step 4: 运行测试确认通过**

```powershell
python -m pytest tests/unit/test_minutes.py -v
```

预期：5 passed。

- [ ] **Step 5: 提交**

```powershell
git add app/providers app/pipeline/minutes.py tests/unit/test_minutes.py
git commit -m "feat: LLM Provider 与结构化纪要生成"
```

# M4 关联、归档与 Worker

### Task 16: 相似度与跨会议关联规则

**Files:**
- Create: `app/core/similarity.py`、`app/pipeline/relations.py`
- Test: `tests/unit/test_relations.py`

- [ ] **Step 1: 写失败的测试**

`tests/unit/test_relations.py`：

```python
import json

from app.core import similarity
from app.pipeline import relations
from app.storage import action_repo, meeting_repo, project_repo


def test_jaccard_basic():
    assert similarity.jaccard("数据同步问题", "数据同步问题") == 1.0
    assert similarity.jaccard("数据同步问题", "预算待定") == 0.0
    assert 0 < similarity.jaccard("整理问题清单", "问题清单整理") < 1


def _previous(conn, minutes, actions):
    pid = project_repo.ensure_project(conn, "项目A")
    mid = meeting_repo.create(
        conn, uid="prev", title="上次会议", project_id=pid,
        recorded_at="2026-11-20 10:00:00", audio_filename="prev.m4a",
        status="done")
    meeting_repo.update_fields(conn, mid,
                               minutes=json.dumps(minutes, ensure_ascii=False))
    action_repo.replace(conn, mid, actions)
    return pid, mid


def _current(conn, pid, minutes):
    mid = meeting_repo.create(
        conn, uid="cur", title="本次会议", project_id=pid,
        recorded_at="2026-11-21 10:00:00", audio_filename="cur.m4a",
        status="relating")
    meeting = meeting_repo.get_by_id(conn, mid)
    return relations.build_relations(conn, meeting, minutes)


def test_pending_carryover_is_reported(conn):
    prev_minutes = {"topics": [{"title": "预算讨论"}]}
    pid, _ = _previous(conn, prev_minutes, [
        {"owner": "张敏", "task": "整理数据同步问题清单", "due": "下周",
         "quote": "我下周先把问题清单整理出来", "segment_ids": [1]},
    ])
    current_minutes = {
        "topics": [{"title": "人员安排"}],
        "actions": [{"owner": "李工", "task": "申请测试资源", "due": "",
                     "quote": "需要提前申请资源", "segment_ids": [2]}],
    }
    result = _current(conn, pid, current_minutes)
    kinds = [r["kind"] for r in result]
    assert "pending_carryover" in kinds
    card = next(r for r in result if r["kind"] == "pending_carryover")
    assert "1 条待办" in card["detail"]
    assert card["quote"] == "整理数据同步问题清单"


def test_matched_action_suppresses_carryover(conn):
    pid, _ = _previous(conn, {"topics": []}, [
        {"owner": "张敏", "task": "整理数据同步问题清单", "due": "下周",
         "quote": "我下周先把问题清单整理出来", "segment_ids": [1]},
    ])
    current_minutes = {
        "topics": [],
        "actions": [{"owner": "张敏", "task": "整理数据同步问题清单", "due": "本周",
                     "quote": "我先把清单整理出来", "segment_ids": [3]}],
    }
    assert _current(conn, pid, current_minutes) == []


def test_repeat_topic_is_reported(conn):
    pid, _ = _previous(conn, {"topics": [{"title": "数据同步问题"}]}, [])
    current_minutes = {"topics": [{"title": "数据同步问题"}], "actions": []}
    result = _current(conn, pid, current_minutes)
    assert [r["kind"] for r in result] == ["repeat_topic"]
    assert result[0]["quote"] == "数据同步问题"
```

- [ ] **Step 2: 运行测试确认失败**

```powershell
python -m pytest tests/unit/test_relations.py -v
```

预期：`ModuleNotFoundError: No module named 'app.core.similarity'`。

- [ ] **Step 3: 实现相似度与关联规则**

`app/core/similarity.py`：

```python
import re


def bigrams(text: str) -> set[str]:
    cleaned = re.sub(r"\s+", "", text or "")
    if len(cleaned) < 2:
        return {cleaned} if cleaned else set()
    return {cleaned[i:i + 2] for i in range(len(cleaned) - 1)}


def jaccard(a: str, b: str) -> float:
    left, right = bigrams(a), bigrams(b)
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)
```

`app/pipeline/relations.py`：

```python
"""只做两类能拿原文举证的关联，不做开放式联想。"""

import json

from app.core import similarity
from app.storage import action_repo, meeting_repo

TASK_MATCH_THRESHOLD = 0.5
TOPIC_MATCH_THRESHOLD = 0.6
MAX_PREVIOUS = 5


def _same_topic(title: str, previous_titles: list[str]) -> bool:
    for previous in previous_titles:
        if not previous or not title:
            continue
        if title == previous or title in previous or previous in title:
            return True
        if similarity.jaccard(title, previous) >= TOPIC_MATCH_THRESHOLD:
            return True
    return False


def build_relations(conn, meeting: dict, minutes: dict) -> list[dict]:
    result: list[dict] = []
    previous_meetings = meeting_repo.previous_done(
        conn, meeting["project_id"], meeting["id"], limit=MAX_PREVIOUS)
    current_actions = minutes.get("actions", [])

    for previous in previous_meetings:
        open_items = action_repo.open_for(conn, previous["id"])
        unmatched = [
            item for item in open_items
            if not any(similarity.jaccard(item["task"], current.get("task", ""))
                       >= TASK_MATCH_THRESHOLD for current in current_actions)
        ]
        if unmatched:
            result.append({
                "target_id": previous["id"],
                "kind": "pending_carryover",
                "detail": f"上次还有 {len(unmatched)} 条待办未见结论",
                "quote": unmatched[0]["task"],
            })

        previous_minutes = json.loads(previous["minutes"]) if previous["minutes"] else {}
        previous_titles = [t.get("title", "")
                           for t in previous_minutes.get("topics", [])]
        for topic in minutes.get("topics", []):
            title = topic.get("title", "")
            if _same_topic(title, previous_titles):
                result.append({
                    "target_id": previous["id"],
                    "kind": "repeat_topic",
                    "detail": f"议题「{title[:18]}」上次也讨论过",
                    "quote": title,
                })
                break
    return result
```

- [ ] **Step 4: 运行测试确认通过**

```powershell
python -m pytest tests/unit/test_relations.py -v
```

预期：4 passed。

- [ ] **Step 5: 提交**

```powershell
git add app/core/similarity.py app/pipeline/relations.py tests/unit/test_relations.py
git commit -m "feat: 两类跨会议关联规则"
```

---

### Task 17: 静态归档与索引页

**Files:**
- Create: `app/pipeline/archive.py`、`app/web/templates/day_index.html`、`root_index.html`
- Test: `tests/integration/test_archive.py`

- [ ] **Step 1: 写失败的测试**

`tests/integration/test_archive.py`：

```python
from app.pipeline import archive
from app.storage import meeting_repo, project_repo


def test_write_meeting_page(cfg, conn):
    pid = project_repo.ensure_project(conn, "项目A")
    meeting_repo.create(
        conn, uid="20261121-100000-abcd", title="测试会", project_id=pid,
        recorded_at="2026-11-21 10:00:00", audio_filename="a.m4a", status="done")
    meeting = meeting_repo.get_by_uid(conn, "20261121-100000-abcd")
    target = archive.write_meeting(cfg, meeting, "<html>纪要</html>")
    assert target == cfg.site_dir / "2026" / "11" / "21" / "20261121-100000-abcd" / "index.html"
    assert "纪要" in target.read_text(encoding="utf-8")


def test_refresh_indices(cfg, conn):
    pid = project_repo.ensure_project(conn, "项目A")
    meeting_repo.create(
        conn, uid="u1", title="第一场", project_id=pid,
        recorded_at="2026-11-21 10:00:00", audio_filename="a.m4a", status="done")
    meeting_repo.create(
        conn, uid="u2", title="第二场", project_id=pid,
        recorded_at="2026-11-20 10:00:00", audio_filename="b.m4a", status="done")
    archive.refresh_indices(cfg)

    day_page = (cfg.site_dir / "2026" / "11" / "21" / "index.html").read_text(encoding="utf-8")
    assert "第一场" in day_page
    root = (cfg.site_dir / "index.html").read_text(encoding="utf-8")
    assert "2026-11-21" in root and "2026-11-20" in root
```

- [ ] **Step 2: 运行测试确认失败**

```powershell
python -m pytest tests/integration/test_archive.py -v
```

预期：`ModuleNotFoundError: No module named 'app.pipeline.archive'`。

- [ ] **Step 3: 实现归档与两个索引模板**

`app/pipeline/archive.py`：

```python
"""静态归档：每场会议一个独立 HTML，另有日索引与总索引。"""

from pathlib import Path

from app.config import Config
from app.storage import db
from app.web import render


def day_dir(cfg: Config, recorded_at: str) -> Path:
    return cfg.site_dir.joinpath(*recorded_at[:10].split("-"))


def write_meeting(cfg: Config, meeting: dict, html: str) -> Path:
    target = day_dir(cfg, meeting["recorded_at"]) / meeting["uid"] / "index.html"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(html, encoding="utf-8")
    return target


def refresh_indices(cfg: Config) -> None:
    conn = db.connect(cfg.db_path)
    try:
        rows = conn.execute(
            "SELECT m.uid, m.title, m.recorded_at, p.name AS project_name"
            " FROM meeting m JOIN project p ON p.id=m.project_id"
            " WHERE m.status='done' ORDER BY m.recorded_at"
        ).fetchall()
    finally:
        conn.close()

    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(row["recorded_at"][:10], []).append(dict(row))

    days = []
    for day in sorted(groups, reverse=True):
        items = sorted(groups[day], key=lambda x: x["recorded_at"], reverse=True)
        html = render.render("day_index.html", day=day, meetings=items,
                             standalone=True)
        target = cfg.site_dir.joinpath(*day.split("-")) / "index.html"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(html, encoding="utf-8")
        days.append({"day": day, "count": len(items)})

    root = render.render("root_index.html", days=days, standalone=True)
    (cfg.site_dir / "index.html").write_text(root, encoding="utf-8")
```

`app/web/templates/day_index.html`：

```html
{% extends "base.html" %}
{% block title %}{{ day }} 会议归档{% endblock %}
{% block content %}
<div class="card">
  <h1 style="margin-top:0">{{ day }} 会议归档</h1>
  {% for m in meetings %}
  <div style="padding:12px 0;border-top:1px solid #e5e6eb">
    <a href="/site/{{ day.replace('-', '/') }}/{{ m.uid }}/index.html">
      <strong>{{ m.title }}</strong>
    </a>
    <div class="muted">{{ m.project_name }} · {{ m.recorded_at }}</div>
  </div>
  {% else %}
  <p class="muted">当天暂无会议。</p>
  {% endfor %}
</div>
{% endblock %}
```

`app/web/templates/root_index.html`：

```html
{% extends "base.html" %}
{% block title %}会议归档{% endblock %}
{% block content %}
<div class="card">
  <h1 style="margin-top:0">会议归档</h1>
  {% for item in days %}
  <div style="padding:10px 0;border-top:1px solid #e5e6eb">
    <a href="/site/{{ item.day.replace('-', '/') }}/index.html">{{ item.day }}</a>
    <span class="muted">{{ item.count }} 场</span>
  </div>
  {% else %}
  <p class="muted">暂无归档。</p>
  {% endfor %}
</div>
{% endblock %}
```

- [ ] **Step 4: 运行测试确认通过**

```powershell
python -m pytest tests/integration/test_archive.py -v
```

预期：2 passed。

- [ ] **Step 5: 提交**

```powershell
git add app/pipeline/archive.py app/web/templates/day_index.html app/web/templates/root_index.html tests/integration/test_archive.py
git commit -m "feat: 静态归档与日期索引"
```

---

### Task 18: 会议详情页与重试接口

**Files:**
- Create: `app/web/context.py`、`app/web/templates/meeting.html`
- Modify: `app/web/pages.py`、`app/api/meetings.py`
- Test: `tests/integration/test_meeting_page.py`

- [ ] **Step 1: 写失败的测试**

`tests/integration/test_meeting_page.py`：

```python
import json

from fastapi.testclient import TestClient

from app.main import create_app
from app.storage import action_repo, db, meeting_repo, project_repo


def _seed(cfg, status="done"):
    conn = db.connect(cfg.db_path)
    try:
        pid = project_repo.ensure_project(conn, "项目A")
        mid = meeting_repo.create(
            conn, uid="20261121-100000-abcd", title="三季度进度会",
            project_id=pid, recorded_at="2026-11-21 10:00:00",
            audio_filename="a.m4a", status=status)
        meeting_repo.update_fields(
            conn, mid,
            transcript=json.dumps([{"idx": 0, "start": 0, "end": 4,
                                    "speaker": "王总", "text": "今天过一下进度。"}],
                                  ensure_ascii=False),
            minutes=json.dumps({
                "summary": "本次会议讨论了进度。",
                "topics": [{"title": "进度", "points": [], "segment_ids": [0]}],
                "decisions": [], "actions": [], "open_issues": [], "people": [],
            }, ensure_ascii=False))
        action_repo.replace(conn, mid, [])
    finally:
        conn.close()
    return mid


def _client(cfg):
    client = TestClient(create_app(cfg, start_threads=False))
    client.__enter__()
    client.post("/login", data={"password": "test-pass"})
    return client


def test_meeting_page_renders_minutes_and_transcript(cfg):
    _seed(cfg)
    client = _client(cfg)
    try:
        html = client.get("/m/20261121-100000-abcd").text
        assert "本次会议讨论了进度。" in html
        assert "今天过一下进度。" in html
        assert "返回列表" in html
    finally:
        client.__exit__(None, None, None)


def test_meeting_page_404(cfg):
    client = _client(cfg)
    try:
        assert client.get("/m/not-exists").status_code == 404
    finally:
        client.__exit__(None, None, None)


def test_retry_moves_failed_to_pending(cfg):
    _seed(cfg, status="failed")
    client = _client(cfg)
    try:
        resp = client.post("/api/meetings/20261121-100000-abcd/retry")
        assert resp.status_code == 200
        assert resp.json()["status"] == "pending"
    finally:
        client.__exit__(None, None, None)


def test_retry_rejects_completed_meeting(cfg):
    _seed(cfg, status="done")
    client = _client(cfg)
    try:
        resp = client.post("/api/meetings/20261121-100000-abcd/retry")
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "invalid_state"
    finally:
        client.__exit__(None, None, None)
```

- [ ] **Step 2: 运行测试确认失败**

```powershell
python -m pytest tests/integration/test_meeting_page.py -v
```

预期：详情页 404 或没有纪要内容。

- [ ] **Step 3: 实现上下文、详情模板与重试接口**

`app/web/context.py`：

```python
import json

from app.core import state
from app.storage import action_repo, relation_repo

MINUTE_TEMPLATES = {
    "standard": {
        "name": "常规会议",
        "sections": ["summary", "topics", "decisions", "actions", "open_issues"],
    },
    "discussion": {
        "name": "座谈交流",
        "sections": ["summary", "topics", "people", "decisions", "actions"],
    },
    "report": {
        "name": "工作汇报",
        "sections": ["summary", "topics", "open_issues", "actions"],
    },
}


def build_context(conn, meeting: dict) -> dict:
    minutes = json.loads(meeting["minutes"]) if meeting["minutes"] else {}
    transcript = json.loads(meeting["transcript"]) if meeting["transcript"] else []
    project = conn.execute(
        "SELECT name FROM project WHERE id=?", (meeting["project_id"],)
    ).fetchone()
    tmpl = MINUTE_TEMPLATES.get(meeting["template_key"],
                                MINUTE_TEMPLATES["standard"])
    return {
        "minutes": minutes,
        "transcript": transcript,
        "actions": action_repo.list_for(conn, meeting["id"]),
        "relations": relation_repo.list_for(conn, meeting["id"]),
        "tmpl": tmpl,
        "project_name": project["name"] if project else "未归类",
        "finished": meeting["status"] == "done",
        "can_retry": state.can_retry(meeting),
    }
```

`app/web/templates/meeting.html`：

```html
{% extends "base.html" %}
{% block title %}{{ m.title }} · 会议记忆{% endblock %}
{% block content %}
<div class="card">
  <div style="display:flex;justify-content:space-between;align-items:start;gap:16px">
    <div>
      <h1 style="margin:0 0 6px">{{ m.title }}</h1>
      <div class="muted">{{ project_name }} · {{ m.recorded_at }} · {{ m.duration_sec|mmss }}</div>
    </div>
    <div style="text-align:right">
      <span class="chip {% if m.status == 'done' %}done{% elif m.status == 'failed' %}failed{% else %}processing{% endif %}">
        {{ labels.get(m.status, m.status) }}
      </span>
      {% if m.error_code %}
      <div class="error" style="margin-top:8px">{{ m.error_code }}：{{ m.error_msg or '' }}</div>
      {% endif %}
      {% if can_retry and not standalone %}
      <button class="btn" id="retry-btn" style="margin-top:10px">重试</button>
      {% endif %}
    </div>
  </div>
  {% if not finished %}
  <p class="muted" style="margin-bottom:0">处理中，页面每 3 秒自动刷新。</p>
  {% endif %}
</div>

{% if minutes %}
{% if 'summary' in tmpl.sections %}
<div class="card" style="margin-top:16px">
  <h2 style="margin-top:0">摘要</h2>
  <p style="margin-bottom:0">{{ minutes.summary }}</p>
</div>
{% endif %}

{% if 'topics' in tmpl.sections and minutes.topics %}
<div class="card" style="margin-top:16px">
  <h2 style="margin-top:0">议题</h2>
  {% for topic in minutes.topics %}
  <div style="margin-bottom:14px">
    <strong>{{ topic.title }}</strong>
    <ul style="margin:6px 0 0;padding-left:20px">
      {% for point in topic.points %}<li>{{ point }}</li>{% endfor %}
    </ul>
  </div>
  {% endfor %}
</div>
{% endif %}

{% if 'decisions' in tmpl.sections and minutes.decisions %}
<div class="card" style="margin-top:16px">
  <h2 style="margin-top:0">决定事项</h2>
  {% for item in minutes.decisions %}
  <div style="margin-bottom:12px">
    <div>{{ item.text }}</div>
    <blockquote class="muted" style="margin:4px 0 0;border-left:3px solid #d0d3d9;padding-left:10px">
      {{ item.quote }}
    </blockquote>
  </div>
  {% endfor %}
</div>
{% endif %}

{% if 'actions' in tmpl.sections and actions %}
<div class="card" style="margin-top:16px">
  <h2 style="margin-top:0">待办事项</h2>
  {% for item in actions %}
  <div style="margin-bottom:12px">
    <div><strong>{{ item.owner }}</strong>：{{ item.task }}
      {% if item.due %}<span class="muted">（{{ item.due }}）</span>{% endif %}
    </div>
    <blockquote class="muted" style="margin:4px 0 0;border-left:3px solid #d0d3d9;padding-left:10px">
      {{ item.quote }}
    </blockquote>
  </div>
  {% endfor %}
</div>
{% endif %}

{% if 'open_issues' in tmpl.sections and minutes.open_issues %}
<div class="card" style="margin-top:16px">
  <h2 style="margin-top:0">待定事项</h2>
  {% for item in minutes.open_issues %}
  <div style="margin-bottom:12px">
    <div>{{ item.text }} <span class="muted">（{{ item.reason }}）</span></div>
  </div>
  {% endfor %}
</div>
{% endif %}

{% if 'people' in tmpl.sections and minutes.people %}
<div class="card" style="margin-top:16px">
  <h2 style="margin-top:0">参会人员</h2>
  <p style="margin-bottom:0">
    {% for person in minutes.people %}{{ person.name }}（{{ person.role }}）{% if not loop.last %} · {% endif %}{% endfor %}
  </p>
</div>
{% endif %}
{% endif %}

{% if relations %}
<div class="card" style="margin-top:16px">
  <h2 style="margin-top:0">与以往会议的关联</h2>
  {% for item in relations %}
  <div style="margin-bottom:14px">
    <strong>{{ '上次待办未落实' if item.kind == 'pending_carryover' else '议题重复' }}</strong>
    <div>{{ item.detail }}</div>
    <blockquote class="muted" style="margin:4px 0;border-left:3px solid #d0d3d9;padding-left:10px">
      {{ item.quote }}
    </blockquote>
    <a href="/m/{{ item.target_uid }}">{{ item.target_title }} · {{ item.target_time }}</a>
  </div>
  {% endfor %}
</div>
{% endif %}

{% if transcript %}
<div class="card" style="margin-top:16px">
  <h2 style="margin-top:0">逐字稿</h2>
  {% for seg in transcript %}
  <div style="margin:8px 0">
    <span class="muted">{{ seg.start|mmss }} {{ seg.speaker }}</span>
    <span>{{ seg.text }}</span>
  </div>
  {% endfor %}
</div>
{% endif %}

<p style="margin-top:20px"><a href="/">返回列表</a></p>

<script>
const retryBtn = document.getElementById("retry-btn");
if (retryBtn) {
  retryBtn.addEventListener("click", async () => {
    const resp = await fetch("/api/meetings/{{ m.uid }}/retry", {method: "POST"});
    if (resp.ok) location.reload();
    else alert("当前状态不允许重试");
  });
}
{% if not finished %}setTimeout(() => location.reload(), 3000);{% endif %}
</script>
{% endblock %}
```

修改 `app/web/pages.py`，追加详情路由（保留原有首页）：

```python
from app.web import context


@router.get("/m/{uid}", response_class=HTMLResponse)
def meeting_page(request: Request, uid: str):
    conn = db.connect(request.app.state.cfg.db_path)
    try:
        meeting = meeting_repo.get_by_uid(conn, uid)
        if not meeting:
            return HTMLResponse("<h1>404</h1><p>会议不存在</p>", status_code=404)
        ctx = context.build_context(conn, meeting)
    finally:
        conn.close()
    return HTMLResponse(render.render(
        "meeting.html", m=meeting, labels=state.STATUS_LABELS,
        standalone=False, **ctx,
    ))
```

修改 `app/api/meetings.py`，追加重试接口：

```python
@router.post("/meetings/{uid}/retry")
def retry_meeting(request: Request, uid: str):
    conn = db.connect(request.app.state.cfg.db_path)
    try:
        m = meeting_repo.get_by_uid(conn, uid)
        if not m:
            raise ApiError(404, "not_found", "会议不存在")
        if not state.can_retry(m):
            raise ApiError(409, "invalid_state", "当前状态不允许重试")
        meeting_repo.reset_for_retry(conn, m["id"])
        return {"status": "pending"}
    finally:
        conn.close()
```

- [ ] **Step 4: 运行测试确认通过**

```powershell
python -m pytest tests/integration/test_meeting_page.py -v
```

预期：4 passed。

- [ ] **Step 5: 提交**

```powershell
git add app/web/context.py app/web/templates/meeting.html app/web/pages.py app/api/meetings.py tests/integration/test_meeting_page.py
git commit -m "feat: 会议详情页与重试接口"
```

---

### Task 19: Worker 全链路与 Maintainer

**Files:**
- Create: `app/pipeline/worker.py`、`app/pipeline/maintainer.py`
- Test: `tests/integration/test_worker.py`

- [ ] **Step 1: 写失败的测试**

`tests/integration/test_worker.py`：

```python
import json
from datetime import datetime, timedelta

from app.pipeline import maintainer, worker
from app.providers.errors import ProviderError
from app.storage import action_repo, db, meeting_repo, project_repo


def _pending(cfg):
    conn = db.connect(cfg.db_path)
    try:
        pid = project_repo.ensure_project(conn, "项目A")
        mid = meeting_repo.create(
            conn, uid="u1", title="测试会", project_id=pid,
            recorded_at="2026-11-21 10:00:00", audio_filename="u1__测试会.m4a")
    finally:
        conn.close()
    (cfg.ready_dir / "u1__测试会.m4a").write_bytes(b"audio")
    return mid


def test_process_once_completes_pipeline(cfg):
    mid = _pending(cfg)
    assert worker.process_once(cfg) is True
    conn = db.connect(cfg.db_path)
    try:
        m = meeting_repo.get_by_id(conn, mid)
        assert m["status"] == "done"
        assert json.loads(m["minutes"])["summary"]
        assert action_repo.list_for(conn, mid)
    finally:
        conn.close()
    assert (cfg.archive_dir / "u1__测试会.m4a").exists()
    assert list(cfg.site_dir.rglob("index.html"))


def test_process_once_returns_false_when_empty(cfg):
    assert worker.process_once(cfg) is False


def test_transient_error_is_requeued(cfg, monkeypatch):
    mid = _pending(cfg)

    def boom(cfg_arg, meeting):
        raise ProviderError("asr_timeout", "超时", transient=True)

    monkeypatch.setattr("app.pipeline.transcribe.run", boom)
    assert worker.process_once(cfg) is True
    conn = db.connect(cfg.db_path)
    try:
        m = meeting_repo.get_by_id(conn, mid)
        assert m["status"] == "pending"
        assert m["retry_count"] == 1
        assert m["next_retry_at"] is not None
        assert m["error_code"] == "asr_timeout"
    finally:
        conn.close()


def test_reclaim_zombies(cfg):
    mid = _pending(cfg)
    conn = db.connect(cfg.db_path)
    try:
        old = (datetime.now() - timedelta(seconds=600)).strftime("%Y-%m-%d %H:%M:%S")
        meeting_repo.update_fields(conn, mid, status="transcribing",
                                   started_at=old, heartbeat_at=old)
    finally:
        conn.close()
    assert maintainer.reclaim_zombies(cfg) == 1
    conn = db.connect(cfg.db_path)
    try:
        m = meeting_repo.get_by_id(conn, mid)
        assert m["status"] == "pending"
        assert m["retry_count"] == 1
    finally:
        conn.close()
```

- [ ] **Step 2: 运行测试确认失败**

```powershell
python -m pytest tests/integration/test_worker.py -v
```

预期：`ModuleNotFoundError: No module named 'app.pipeline.worker'`。

- [ ] **Step 3: 实现 Worker 与 Maintainer**

`app/pipeline/worker.py`：

```python
"""任务执行器：领取 → 转写 → 纪要 → 关联 → 归档。"""

import json
import shutil
import threading
import traceback
from datetime import datetime, timedelta

from app.config import Config
from app.core import state
from app.core.logging import log_event
from app.pipeline import archive, minutes as minutes_pipeline, relations, transcribe
from app.pipeline.minutes import MinutesValidationError
from app.providers.errors import ProviderError
from app.storage import action_repo, db, meeting_repo, relation_repo
from app.web import context, render


def _finalize(cfg: Config, conn, meeting: dict) -> None:
    audio = cfg.ready_dir / meeting["audio_filename"]
    if audio.exists():
        shutil.move(str(audio), str(cfg.archive_dir / audio.name))
    fresh = meeting_repo.get_by_id(conn, meeting["id"])
    ctx = context.build_context(conn, fresh)
    html = render.render("meeting.html", m=fresh, standalone=True,
                         labels=state.STATUS_LABELS, **ctx)
    archive.write_meeting(cfg, fresh, html)
    archive.refresh_indices(cfg)


def _minutes_failed(conn, meeting: dict, code: str, message: str) -> None:
    meeting_repo.set_status(conn, meeting["id"], "done", code, message[:500])


def _run_relations(cfg, conn, meeting):
    try:
        meeting_repo.set_status(conn, meeting["id"], "relating")
        fresh = meeting_repo.get_by_id(conn, meeting["id"])
        data = json.loads(fresh["minutes"])
        relation_repo.replace(conn, meeting["id"],
                              relations.build_relations(conn, fresh, data))
        meeting_repo.set_status(conn, meeting["id"], "done")
    except Exception as exc:
        traceback.print_exc()
        log_event("error", "relation_failed", uid=meeting["uid"],
                  detail=str(exc))
        meeting_repo.set_status(conn, meeting["id"], "done",
                                "relation_failed", str(exc)[:500])


def _process(cfg: Config, conn, meeting: dict) -> None:
    stage = state.resume_stage(meeting["transcript"], meeting["minutes"])
    log_event("info", "stage", uid=meeting["uid"], stage=stage)
    segments = json.loads(meeting["transcript"]) if meeting["transcript"] else None

    if stage == "transcribe":
        segments = transcribe.run(cfg, meeting)
        meeting_repo.update_fields(
            conn, meeting["id"],
            transcript=json.dumps(segments, ensure_ascii=False),
            duration_sec=int(segments[-1]["end"]) if segments else 0,
        )
        meeting_repo.set_status(conn, meeting["id"], "minuting")
    elif stage == "minutes":
        meeting_repo.set_status(conn, meeting["id"], "minuting")

    if stage in {"transcribe", "minutes"}:
        try:
            data = minutes_pipeline.generate(cfg, segments or [],
                                             meeting["template_key"])
        except MinutesValidationError as exc:
            _minutes_failed(conn, meeting, "llm_bad_json", str(exc))
            _finalize(cfg, conn, meeting)
            return
        except ProviderError as exc:
            if exc.transient:
                raise
            _minutes_failed(conn, meeting, exc.code, exc.message)
            _finalize(cfg, conn, meeting)
            return
        action_repo.replace(conn, meeting["id"], data.get("actions", []))
        meeting_repo.update_fields(
            conn, meeting["id"],
            minutes=json.dumps(data, ensure_ascii=False),
            error_code=None, error_msg=None,
        )

    _run_relations(cfg, conn, meeting)
    _finalize(cfg, conn, meeting)


def _heartbeat(cfg: Config, meeting_id: int, stop: threading.Event) -> None:
    while not stop.wait(cfg.heartbeat_interval):
        try:
            conn = db.connect(cfg.db_path)
            try:
                meeting_repo.touch(conn, meeting_id)
            finally:
                conn.close()
        except Exception:
            traceback.print_exc()


def _retry_or_fail(cfg: Config, conn, meeting: dict, exc: ProviderError) -> None:
    if exc.transient and meeting["retry_count"] < cfg.auto_retry_max:
        log_event("warn", "retry", uid=meeting["uid"], code=exc.code)
        next_at = (datetime.now() + timedelta(seconds=cfg.retry_backoff_sec))
        meeting_repo.update_fields(
            conn, meeting["id"], status="pending",
            retry_count=meeting["retry_count"] + 1,
            next_retry_at=next_at.strftime("%Y-%m-%d %H:%M:%S"),
            error_code=exc.code, error_msg=exc.message,
            started_at=None, heartbeat_at=None,
        )
    else:
        log_event("error", "failed", uid=meeting["uid"], code=exc.code)
        meeting_repo.set_status(conn, meeting["id"], "failed",
                                exc.code, exc.message[:500])


def process_once(cfg: Config) -> bool:
    conn = db.connect(cfg.db_path)
    try:
        meeting = meeting_repo.claim_next(conn)
        if not meeting:
            return False
        stop = threading.Event()
        heartbeat = threading.Thread(target=_heartbeat,
                                     args=(cfg, meeting["id"], stop), daemon=True)
        heartbeat.start()
        try:
            _process(cfg, conn, meeting)
        except ProviderError as exc:
            _retry_or_fail(cfg, conn, meeting, exc)
        except Exception:
            traceback.print_exc()
            log_event("error", "exception", uid=meeting["uid"],
                      detail=traceback.format_exc())
            meeting_repo.set_status(conn, meeting["id"], "failed",
                                    "internal", "处理异常，详见日志")
        finally:
            stop.set()
            heartbeat.join(timeout=1)
        return True
    finally:
        conn.close()


def start(cfg: Config, stop: threading.Event) -> threading.Thread:
    def loop() -> None:
        while not stop.is_set():
            try:
                if not process_once(cfg):
                    stop.wait(1.0)
            except Exception:
                traceback.print_exc()
                stop.wait(1.0)

    thread = threading.Thread(target=loop, daemon=True, name="worker")
    thread.start()
    return thread
```

`app/pipeline/maintainer.py`：

```python
"""后台维护：僵尸任务回收与残片清理。"""

import threading
import time
import traceback
from datetime import datetime, timedelta

from app.config import Config
from app.storage import db, files, meeting_repo

MAX_RECLAIMS = 3


def reclaim_zombies(cfg: Config, now: datetime | None = None) -> int:
    moment = now or datetime.now()
    cutoff = (moment - timedelta(seconds=cfg.zombie_timeout)).strftime(
        "%Y-%m-%d %H:%M:%S")
    conn = db.connect(cfg.db_path)
    try:
        rows = conn.execute(
            "SELECT id, retry_count FROM meeting"
            " WHERE status IN ('transcribing','minuting','relating')"
            " AND COALESCE(heartbeat_at, started_at, updated_at) < ?",
            (cutoff,),
        ).fetchall()
        for row in rows:
            if row["retry_count"] >= MAX_RECLAIMS:
                meeting_repo.set_status(conn, row["id"], "failed",
                                        "worker_timeout", "处理超时 3 次")
            else:
                meeting_repo.update_fields(
                    conn, row["id"], status="pending",
                    retry_count=row["retry_count"] + 1,
                    error_code="worker_timeout",
                    error_msg="心跳超时，已重新排队",
                    started_at=None, heartbeat_at=None,
                )
        return len(rows)
    finally:
        conn.close()


def fail_stale_uploads(cfg: Config, now: datetime | None = None) -> int:
    moment = now or datetime.now()
    cutoff = (moment - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
    conn = db.connect(cfg.db_path)
    try:
        rows = conn.execute(
            "SELECT id FROM meeting WHERE status='uploading' AND created_at < ?",
            (cutoff,),
        ).fetchall()
        for row in rows:
            meeting_repo.set_status(conn, row["id"], "failed",
                                    "file_missing", "上传超过 24 小时未完成")
        return len(rows)
    finally:
        conn.close()


def cleanup_parts(cfg: Config, now_ts: float | None = None) -> int:
    moment = time.time() if now_ts is None else now_ts
    cutoff = moment - 24 * 3600
    removed = 0
    for path in cfg.inbox_dir.glob("*.part"):
        if path.stat().st_mtime < cutoff:
            path.unlink(missing_ok=True)
            removed += 1
    for meta in cfg.inbox_dir.glob("*.json"):
        audio = [p for p in cfg.inbox_dir.glob(f"{meta.stem}.*")
                 if p.suffix.lower() in files.AUDIO_SUFFIXES]
        if not audio and meta.stat().st_mtime < cutoff:
            meta.unlink(missing_ok=True)
            removed += 1
    return removed


def start(cfg: Config, stop: threading.Event) -> threading.Thread:
    def loop() -> None:
        while not stop.is_set():
            try:
                reclaim_zombies(cfg)
                fail_stale_uploads(cfg)
                cleanup_parts(cfg)
            except Exception:
                traceback.print_exc()
            stop.wait(60)

    thread = threading.Thread(target=loop, daemon=True, name="maintainer")
    thread.start()
    return thread
```

- [ ] **Step 4: 运行测试确认通过**

```powershell
python -m pytest tests/integration/test_worker.py -v
```

预期：4 passed。

- [ ] **Step 5: 提交**

```powershell
git add app/pipeline/worker.py app/pipeline/maintainer.py tests/integration/test_worker.py
git commit -m "feat: 处理流水线 Worker 与僵尸回收"
```

---

# M5 验收与交付

### Task 20: 端到端集成测试

**Files:**
- Create: `tests/integration/test_e2e_mock.py`
- Test: 同上

- [ ] **Step 1: 写失败的测试**

`tests/integration/test_e2e_mock.py`：

```python
from fastapi.testclient import TestClient

from app.main import create_app
from app.pipeline import harvester, worker
from app.storage import db, meeting_repo, relation_repo


def test_upload_to_archive_and_relation(cfg):
    app = create_app(cfg, start_threads=False)
    with TestClient(app) as client:
        client.post("/login", data={"password": "test-pass"})

        first = client.post(
            "/api/meetings",
            files={"file": ("一季会.m4a", b"audio-1", "audio/mp4")},
            data={"title": "一季会", "project_name": "项目A"},
        ).json()["uid"]
        assert harvester.harvest_once(cfg) == 1
        assert worker.process_once(cfg) is True

        conn = db.connect(cfg.db_path)
        try:
            m1 = meeting_repo.get_by_uid(conn, first)
            assert m1["status"] == "done"
        finally:
            conn.close()

        day = m1["recorded_at"][:10].split("-")
        archive_file = cfg.site_dir.joinpath(*day, first, "index.html")
        assert archive_file.exists()
        assert "本次会议" in archive_file.read_text(encoding="utf-8")

        second = client.post(
            "/api/meetings",
            files={"file": ("二季会.m4a", b"audio-2", "audio/mp4")},
            data={"title": "二季会", "project_name": "项目A"},
        ).json()["uid"]
        assert harvester.harvest_once(cfg) == 1
        assert worker.process_once(cfg) is True

        conn = db.connect(cfg.db_path)
        try:
            m2 = meeting_repo.get_by_uid(conn, second)
            assert m2["status"] == "done"
            rels = relation_repo.list_for(conn, m2["id"])
            assert rels, "第二场同项目会议应产生关联"
            assert all(r["quote"] for r in rels)
        finally:
            conn.close()

        detail = client.get(f"/m/{second}").text
        assert "与以往会议的关联" in detail
```

- [ ] **Step 2: 运行测试确认失败（回看是否已满足）**

```powershell
python -m pytest tests/integration/test_e2e_mock.py -v
```

预期：如果前序任务全部完成，可能直接通过；若失败，按断言定位缺失环节。此测试是验收基线，不为了让它红而制造问题。

- [ ] **Step 3: 全量回归**

```powershell
python -m pytest -v
```

预期：全部通过。若失败，先修当前失败项，不允许跳过。

- [ ] **Step 4: 手工验收（按规格 2.4 六条）**

```powershell
$env:APP_PASSWORD="demo1234"
$env:DATA_DIR="./data"
$env:SITE_DIR="./site"
python -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
```

用浏览器完成：

1. 上传任意 `.m4a`，3 秒内列表出现“接收中/排队中”。
2. mock 模式下等待状态变为“已完成”，详情页有摘要、待办、逐字稿。
3. 同项目再上传一场，第二场详情出现关联卡片且带引用。
4. 打开 `site/YYYY/MM/DD/{uid}/index.html` 与当日 `index.html`。
5. 处理中强杀进程并重启，任务自动恢复。
6. 向 `data/inbox` 放一个 `.part` 文件，等待两个扫描周期，确认不产生会议。

- [ ] **Step 5: 提交**

```powershell
git add tests/integration/test_e2e_mock.py
git commit -m "test: 端到端验收基线"
```

---

### Task 21: 部署件与删除脚本

**Files:**
- Create: `deploy/systemd/mm.service`、`deploy/nginx/mm.conf`、`deploy/backup.sh`、`deploy/delete_meeting.py`、`config/hotwords.txt`
- Test: `tests/integration/test_delete_meeting.py`

- [ ] **Step 1: 写失败的测试**

`tests/integration/test_delete_meeting.py`：

```python
import importlib.util
from pathlib import Path

from app.pipeline import archive
from app.storage import db, meeting_repo, project_repo

ROOT = Path(__file__).resolve().parents[2]


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "delete_meeting", ROOT / "deploy" / "delete_meeting.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_delete_meeting_removes_db_files_and_archive(cfg, conn):
    pid = project_repo.ensure_project(conn, "项目A")
    meeting_repo.create(
        conn, uid="u1", title="待删会议", project_id=pid,
        recorded_at="2026-11-21 10:00:00", audio_filename="u1__待删会议.m4a",
        status="done")
    meeting = meeting_repo.get_by_uid(conn, "u1")
    (cfg.archive_dir / meeting["audio_filename"]).write_bytes(b"audio")
    archive.write_meeting(cfg, meeting, "<html>待删</html>")
    archive.refresh_indices(cfg)

    module = _load_module()
    assert module.delete(cfg, "u1") == 0
    assert meeting_repo.get_by_uid(conn, "u1") is None
    assert not (cfg.archive_dir / meeting["audio_filename"]).exists()
    assert not (cfg.site_dir / "2026" / "11" / "21" / "u1").exists()
```

- [ ] **Step 2: 运行测试确认失败**

```powershell
python -m pytest tests/integration/test_delete_meeting.py -v
```

预期：`FileNotFoundError: deploy/delete_meeting.py`。

- [ ] **Step 3: 写部署件与删除脚本**

`config/hotwords.txt`：

```text
王总
李工
张敏
三季度
数据同步
```

`deploy/delete_meeting.py`：

```python
"""按 uid 删除会议：数据库记录、音频、静态归档，并刷新索引。"""

import argparse
import shutil
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def delete(cfg, uid: str) -> int:
    conn = sqlite3.connect(str(cfg.db_path))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM meeting WHERE uid=?", (uid,)).fetchone()
        if not row:
            print(f"未找到会议：{uid}")
            return 1
        meeting_id = row["id"]
        conn.execute("DELETE FROM relation WHERE meeting_id=? OR target_id=?",
                     (meeting_id, meeting_id))
        conn.execute("DELETE FROM action_item WHERE meeting_id=?", (meeting_id,))
        conn.execute("DELETE FROM meeting WHERE id=?", (meeting_id,))
        conn.commit()
    finally:
        conn.close()

    for base in (cfg.archive_dir, cfg.ready_dir, cfg.inbox_dir):
        for path in base.glob(f"{uid}__*"):
            path.unlink(missing_ok=True)

    day = row["recorded_at"][:10].split("-")
    shutil.rmtree(cfg.site_dir.joinpath(*day, uid), ignore_errors=True)

    from app.pipeline import archive
    archive.refresh_indices(cfg)
    print(f"已删除：{uid}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="删除指定会议及其归档")
    parser.add_argument("uid")
    args = parser.parse_args()
    from app.config import Config
    config = Config.from_env()
    problems = config.validate()
    if problems:
        print("配置错误：" + "；".join(problems))
        return 2
    return delete(config, args.uid)


if __name__ == "__main__":
    raise SystemExit(main())
```

`deploy/systemd/mm.service`：

```ini
[Unit]
Description=Meeting Memory
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/meeting-memory
EnvironmentFile=/opt/meeting-memory/.env
ExecStart=/opt/meeting-memory/.venv/bin/python -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000 --workers 1
Restart=always
RestartSec=3
User=mm
Group=mm

[Install]
WantedBy=multi-user.target
```

`deploy/nginx/mm.conf`：

```nginx
server {
    listen 80;
    server_name mm.internal;

    client_max_body_size 520m;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 900s;
    }

    location /site/ {
        alias /opt/meeting-memory/site/;
        autoindex off;
        allow 10.0.0.0/8;
        allow 172.16.0.0/12;
        allow 192.168.0.0/16;
        deny all;
    }
}
```

`deploy/backup.sh`：

```bash
#!/bin/bash
set -euo pipefail

BASE=/opt/meeting-memory
DEST=/backup/meeting-memory/$(date +%F)
mkdir -p "$DEST"

sqlite3 "$BASE/data/app.db" ".backup '$DEST/app.db'"
rsync -a "$BASE/data/archive" "$BASE/site" "$DEST/"

find /backup/meeting-memory -mindepth 1 -maxdepth 1 -type d -mtime +30 -exec rm -rf {} +
```

- [ ] **Step 4: 运行删除脚本测试**

```powershell
python -m pytest tests/integration/test_delete_meeting.py -v
```

预期：1 passed。

- [ ] **Step 5: 真实环境前置检查（服务器上执行）**

```bash
sudo apt install -y ffmpeg
python -m pip install -r requirements.txt -r requirements-asr.txt
python -c "from modelscope import snapshot_download as d; \
d('iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch', local_dir='models/funasr/asr'); \
d('iic/speech_fsmn_vad_zh-cn-16k-common-pytorch', local_dir='models/funasr/vad'); \
d('iic/punc_ct-transformer_zh-cn-common-vocab272727-pytorch', local_dir='models/funasr/punc'); \
d('iic/speech_campplus_sv_zh-cn_16k-common', local_dir='models/funasr/spk')"
```

然后在 `.env` 中设置 `ASR_BACKEND=funasr`、`LLM_PROVIDER=openai` 及对应地址模型，重启服务，用一段 10 分钟、3 人对话录音验证：说话人数正确、时间戳单调、纪要引用可对照原文。

GPU 环境需按服务器的 CUDA 版本先安装对应 torch，再执行上面的 `requirements-asr.txt`。部署时把 `.env.example` 复制为 `.env`，务必修改 `APP_PASSWORD` 并显式设置 `COOKIE_SECRET`。

- [ ] **Step 6: 提交**

```powershell
git add deploy config tests/integration/test_delete_meeting.py
git commit -m "chore: 部署件、备份与删除脚本"
```

---

## 计划自检

- **规格覆盖**：状态机（Task 4）、原子落盘（Task 7/11）、上传与目录监听（Task 10/11）、ASR 与分人（Task 13/14）、纪要 schema 与分块（Task 15）、关联（Task 16）、归档与索引（Task 17）、重试与降级（Task 18/19）、心跳与僵尸回收（Task 19）、部署与合规依赖（Task 21）均有对应任务。
- **占位符扫描**：无 TBD/TODO；所有代码步骤均给出完整实现。
- **命名一致性**：`harvest_once`、`process_once`、`resume_stage`、`can_retry`、`build_context`、`build_relations`、`refresh_indices` 在任务间签名一致。
- **未覆盖的 P1/P2**：原文回听、项目聚合、待办推送、人工修订、多用户权限均不在本计划内，符合规格范围。

---

## 执行方式（二选一）

1. **Subagent-Driven（推荐）**：每个 Task 派一个全新子代理执行，任务间做一次审查，问题不累积。
2. **Inline Execution**：在当前会话按 `executing-plans` 批量执行，每完成一个里程碑停下来检查。


