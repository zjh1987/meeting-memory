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
