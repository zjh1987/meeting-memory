import sqlite3
from datetime import datetime

FALLBACK_NAME = "未归类"
MAX_NAME_LEN = 64


def ensure_project(conn: sqlite3.Connection, name: str) -> int:
    name = (name or "").strip() or FALLBACK_NAME
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


def list_with_counts(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT p.*, (SELECT COUNT(*) FROM meeting m WHERE m.project_id=p.id)"
        " AS meeting_count FROM project p ORDER BY p.name"
    ).fetchall()
    return [dict(r) for r in rows]


def get(conn: sqlite3.Connection, project_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM project WHERE id=?", (project_id,)).fetchone()
    return dict(row) if row else None


def create(conn: sqlite3.Connection, name: str) -> dict:
    value = _clean_name(name)
    if conn.execute("SELECT 1 FROM project WHERE name=?", (value,)).fetchone():
        raise ValueError(f"项目已存在：{value}")
    cur = conn.execute(
        "INSERT INTO project (name, created_at) VALUES (?, ?)",
        (value, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
    )
    return get(conn, int(cur.lastrowid))


def rename(conn: sqlite3.Connection, project_id: int, name: str) -> dict:
    value = _clean_name(name)
    row = get(conn, project_id)
    if row is None:
        raise LookupError("项目不存在")
    if row["name"] == value:
        return row
    if conn.execute("SELECT 1 FROM project WHERE name=? AND id<>?",
                    (value, project_id)).fetchone():
        raise ValueError(f"项目已存在：{value}")
    conn.execute("UPDATE project SET name=? WHERE id=?", (value, project_id))
    return get(conn, project_id)


def count_meetings(conn: sqlite3.Connection, project_id: int) -> int:
    row = conn.execute("SELECT COUNT(*) AS n FROM meeting WHERE project_id=?",
                       (project_id,)).fetchone()
    return int(row["n"] if row else 0)


def move_meetings(conn: sqlite3.Connection, source_id: int, target_id: int) -> int:
    if source_id == target_id:
        raise ValueError("不能转移到原项目")
    if get(conn, target_id) is None:
        raise LookupError("目标项目不存在")
    cur = conn.execute("UPDATE meeting SET project_id=? WHERE project_id=?",
                       (target_id, source_id))
    return int(cur.rowcount)


def delete(conn: sqlite3.Connection, project_id: int,
           move_to: int | None = None) -> dict:
    row = get(conn, project_id)
    if row is None:
        raise LookupError("项目不存在")
    total = count_meetings(conn, project_id)
    if total and move_to is None:
        raise ValueError(f"该项目下仍有 {total} 场会议，请先指定要转移到的项目")
    moved = 0
    conn.execute("BEGIN")
    try:
        if total:
            moved = move_meetings(conn, project_id, move_to)
            # move_meetings 已确认目标存在；这里再校验一次目标未被本事务删除。
        conn.execute("DELETE FROM project WHERE id=?", (project_id,))
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return {"deleted": row["name"], "moved": moved}


def _clean_name(name: str) -> str:
    value = (name or "").strip()
    if not value:
        raise ValueError("项目名称不能为空")
    if len(value) > MAX_NAME_LEN:
        raise ValueError(f"项目名称不能超过 {MAX_NAME_LEN} 个字符")
    return value
