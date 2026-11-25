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


def list_for(conn: sqlite3.Connection, meeting_id: int,
             owner_id: int | None = None) -> list[dict]:
    sql = ("SELECT r.*, m.title AS target_title, m.uid AS target_uid,"
           " m.recorded_at AS target_time"
           " FROM relation r JOIN meeting m ON m.id=r.target_id"
           " WHERE r.meeting_id=?")
    params: list = [meeting_id]
    if owner_id is not None:
        sql += " AND m.owner_id=?"
        params.append(owner_id)
    rows = conn.execute(sql + " ORDER BY r.id", params).fetchall()
    return [dict(r) for r in rows]
