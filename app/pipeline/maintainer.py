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
