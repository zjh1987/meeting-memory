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
