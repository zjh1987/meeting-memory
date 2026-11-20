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
