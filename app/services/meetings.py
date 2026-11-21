"""会议级操作：删除、结案、重新生成纪要。"""

import shutil
import traceback

from app.config import Config
from app.core.logging import log_event
from app.storage import db, meeting_repo


def _row(conn, uid: str) -> dict | None:
    return meeting_repo.get_by_uid(conn, uid)


def set_closed(cfg: Config, uid: str, closed: bool) -> dict:
    conn = db.connect(cfg.db_path)
    try:
        row = _row(conn, uid)
        if row is None:
            raise LookupError("会议不存在")
        meeting_repo.update_fields(conn, row["id"], closed=1 if closed else 0)
        return {"uid": uid, "closed": bool(closed)}
    finally:
        conn.close()


def regenerate_minutes(cfg: Config, uid: str) -> dict:
    conn = db.connect(cfg.db_path)
    try:
        row = _row(conn, uid)
        if row is None:
            raise LookupError("会议不存在")
        if row["status"] in {"uploading", "pending", "transcribing",
                             "minuting", "relating"}:
            raise ValueError("会议正在处理中，不能重新生成")
        if not row["transcript"]:
            raise ValueError("该会议还没有逐字稿，无法只重生成纪要")
        conn.execute("DELETE FROM action_item WHERE meeting_id=?", (row["id"],))
        conn.execute("DELETE FROM relation WHERE meeting_id=?", (row["id"],))
        meeting_repo.update_fields(
            conn, row["id"], minutes=None, error_code=None, error_msg=None,
            finished_at=None, started_at=None, heartbeat_at=None,
        )
        meeting_repo.set_status(conn, row["id"], "pending")
        log_event("info", "regenerate", uid=uid)
        return {"uid": uid, "status": "pending"}
    finally:
        conn.close()


def delete_meeting(cfg: Config, uid: str) -> tuple[bool, str]:
    conn = db.connect(cfg.db_path)
    try:
        row = _row(conn, uid)
        if row is None:
            return False, "会议不存在"
        meeting_id = row["id"]
        conn.execute("DELETE FROM relation WHERE meeting_id=? OR target_id=?",
                     (meeting_id, meeting_id))
        conn.execute("DELETE FROM action_item WHERE meeting_id=?", (meeting_id,))
        conn.execute("DELETE FROM meeting WHERE id=?", (meeting_id,))
    finally:
        conn.close()

    for base in (cfg.archive_dir, cfg.ready_dir, cfg.inbox_dir):
        for path in base.glob(f"{uid}__*"):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                traceback.print_exc()

    from app.pipeline import archive
    shutil.rmtree(archive.day_dir(cfg, row["recorded_at"]) / uid,
                  ignore_errors=True)
    archive.refresh_indices(cfg)
    log_event("info", "delete_meeting", uid=uid)
    return True, f"已删除：{uid}"
