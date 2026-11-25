"""会议仓储。claim_next 用 BEGIN IMMEDIATE + 条件更新保证不重复领取。"""

import sqlite3
from datetime import datetime

from app.core import state

FIELDS = {
    "title", "project_id", "template_key", "recorded_at", "duration_sec",
    "audio_filename", "audio_size", "status", "error_code", "error_msg",
    "retry_count", "next_retry_at", "transcript", "minutes", "closed",
    "asr_seconds", "audio_seconds", "owner_id", "title_auto",
    "started_at", "finished_at", "heartbeat_at",
}


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def create(conn, *, uid, title, project_id, recorded_at, audio_filename,
           audio_size=0, template_key="standard", status="pending",
           owner_id: int | None = None, title_auto: int = 0) -> int:
    ts = now_str()
    cur = conn.execute(
        "INSERT INTO meeting (uid, title, project_id, template_key, recorded_at,"
        " audio_filename, audio_size, status, owner_id, title_auto,"
        " created_at, updated_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (uid, title, project_id, template_key, recorded_at,
         audio_filename, audio_size, status, owner_id, title_auto, ts, ts),
    )
    return int(cur.lastrowid)


def get_by_uid(conn, uid: str) -> dict | None:
    row = conn.execute("SELECT * FROM meeting WHERE uid=?", (uid,)).fetchone()
    return dict(row) if row else None


def get_by_id(conn, meeting_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM meeting WHERE id=?", (meeting_id,)).fetchone()
    return dict(row) if row else None


def list_page(conn, project_id=None, status=None, date=None, page=1, size=20,
              owner_id=None):
    where, params = [], []
    if owner_id is not None:
        where.append("m.owner_id=?")
        params.append(owner_id)
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
        " AND closed=0 ORDER BY id DESC LIMIT ?",
        (project_id, before_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def relation_candidates(conn, project_id: int, before_id: int,
                        since: str | None = None, owner_id: int | None = None,
                        limit: int = 60) -> list[dict]:
    """关联候选：同项目、已完成、未结案，按录音时间从新到旧。"""
    where = ["project_id=?", "id<?", "status='done'", "closed=0"]
    params: list = [project_id, before_id]
    if owner_id is not None:
        where.append("owner_id=?")
        params.append(owner_id)
    if since:
        where.append("recorded_at>=?")
        params.append(since)
    rows = conn.execute(
        "SELECT * FROM meeting WHERE " + " AND ".join(where)
        + " ORDER BY recorded_at DESC, id DESC LIMIT ?",
        params + [limit],
    ).fetchall()
    return [dict(r) for r in rows]
