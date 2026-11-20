"""SQLite 存储层。

meeting.status 同时充当任务队列：pending 表示待处理，worker 领取后改成处理中。
换句话说，任务表不需要单独一张，会议记录本身就是任务。
"""

import json
import sqlite3
from datetime import datetime

from config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS meeting (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    uid          TEXT NOT NULL UNIQUE,
    title        TEXT NOT NULL,
    project      TEXT NOT NULL DEFAULT '未归类',
    template_key TEXT NOT NULL DEFAULT 'standard',
    recorded_at  TEXT NOT NULL,
    duration_sec INTEGER NOT NULL DEFAULT 0,
    audio_path   TEXT,
    status       TEXT NOT NULL DEFAULT 'pending',
    error        TEXT,
    transcript   TEXT,
    minutes      TEXT,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS action_item (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    meeting_id INTEGER NOT NULL,
    owner      TEXT,
    task       TEXT NOT NULL,
    due        TEXT,
    quote      TEXT,
    status     TEXT NOT NULL DEFAULT 'open'
);

CREATE TABLE IF NOT EXISTS relation (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    meeting_id INTEGER NOT NULL,
    target_id  INTEGER NOT NULL,
    kind       TEXT NOT NULL,
    detail     TEXT,
    quote      TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_meeting_project ON meeting(project);
CREATE INDEX IF NOT EXISTS idx_meeting_status ON meeting(status);
CREATE INDEX IF NOT EXISTS idx_action_meeting ON action_item(meeting_id);
CREATE INDEX IF NOT EXISTS idx_relation_meeting ON relation(meeting_id);
"""


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _connect() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH, timeout=15)
    c.row_factory = sqlite3.Row
    return c


def init_db() -> None:
    c = _connect()
    try:
        c.executescript(SCHEMA)
        c.commit()
    finally:
        c.close()


def create_meeting(uid: str, title: str, project: str, audio_path: str,
                   recorded_at: str, duration_sec: int = 0) -> int:
    now = _now()
    c = _connect()
    try:
        cur = c.execute(
            "INSERT INTO meeting (uid, title, project, recorded_at, duration_sec,"
            " audio_path, status, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,'pending',?,?)",
            (uid, title, project, recorded_at, duration_sec, audio_path, now, now),
        )
        c.commit()
        return int(cur.lastrowid)
    finally:
        c.close()


def list_meetings(limit: int = 100) -> list[dict]:
    c = _connect()
    try:
        rows = c.execute(
            "SELECT * FROM meeting ORDER BY recorded_at DESC, id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        c.close()


def get_meeting(uid: str) -> dict | None:
    c = _connect()
    try:
        row = c.execute("SELECT * FROM meeting WHERE uid=?", (uid,)).fetchone()
        return dict(row) if row else None
    finally:
        c.close()


def claim_next_pending() -> dict | None:
    """领取一条待处理会议。单 worker 场景下够用。"""
    c = _connect()
    try:
        row = c.execute(
            "SELECT * FROM meeting WHERE status='pending' ORDER BY id LIMIT 1"
        ).fetchone()
        if not row:
            return None
        c.execute(
            "UPDATE meeting SET status='transcribing', updated_at=? WHERE id=?",
            (_now(), row["id"]),
        )
        c.commit()
        return dict(row)
    finally:
        c.close()


def set_status(meeting_id: int, status: str, error: str | None = None) -> None:
    c = _connect()
    try:
        c.execute(
            "UPDATE meeting SET status=?, error=?, updated_at=? WHERE id=?",
            (status, error, _now(), meeting_id),
        )
        c.commit()
    finally:
        c.close()


def save_transcript(meeting_id: int, segments: list[dict]) -> None:
    duration = 0
    if segments:
        duration = int(segments[-1].get("end") or 0)
    c = _connect()
    try:
        c.execute(
            "UPDATE meeting SET transcript=?, duration_sec=?, updated_at=? WHERE id=?",
            (json.dumps(segments, ensure_ascii=False), duration, _now(), meeting_id),
        )
        c.commit()
    finally:
        c.close()


def save_minutes(meeting_id: int, minutes: dict, template_key: str) -> None:
    c = _connect()
    try:
        c.execute(
            "UPDATE meeting SET minutes=?, template_key=?, updated_at=? WHERE id=?",
            (json.dumps(minutes, ensure_ascii=False), template_key, _now(), meeting_id),
        )
        c.commit()
    finally:
        c.close()


def replace_actions(meeting_id: int, actions: list[dict]) -> None:
    c = _connect()
    try:
        c.execute("DELETE FROM action_item WHERE meeting_id=?", (meeting_id,))
        for a in actions:
            c.execute(
                "INSERT INTO action_item (meeting_id, owner, task, due, quote)"
                " VALUES (?,?,?,?,?)",
                (meeting_id, a.get("owner", ""), a.get("task", ""),
                 a.get("due", ""), a.get("quote", "")),
            )
        c.commit()
    finally:
        c.close()


def get_actions(meeting_id: int) -> list[dict]:
    c = _connect()
    try:
        rows = c.execute(
            "SELECT * FROM action_item WHERE meeting_id=? ORDER BY id", (meeting_id,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        c.close()


def previous_in_project(project: str, before_id: int, limit: int = 5) -> list[dict]:
    c = _connect()
    try:
        rows = c.execute(
            "SELECT * FROM meeting WHERE project=? AND id<? AND status='done'"
            " ORDER BY id DESC LIMIT ?",
            (project, before_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        c.close()


def open_actions(meeting_id: int) -> list[dict]:
    c = _connect()
    try:
        rows = c.execute(
            "SELECT * FROM action_item WHERE meeting_id=? AND status='open' ORDER BY id",
            (meeting_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        c.close()


def replace_relations(meeting_id: int, relations: list[dict]) -> None:
    c = _connect()
    try:
        c.execute("DELETE FROM relation WHERE meeting_id=?", (meeting_id,))
        for r in relations:
            c.execute(
                "INSERT INTO relation (meeting_id, target_id, kind, detail, quote, created_at)"
                " VALUES (?,?,?,?,?,?)",
                (meeting_id, r["target_id"], r["kind"], r.get("detail", ""),
                 r.get("quote", ""), _now()),
            )
        c.commit()
    finally:
        c.close()


def get_relations(meeting_id: int) -> list[dict]:
    c = _connect()
    try:
        rows = c.execute(
            "SELECT r.*, m.title AS target_title, m.uid AS target_uid,"
            " m.recorded_at AS target_time"
            " FROM relation r JOIN meeting m ON m.id = r.target_id"
            " WHERE r.meeting_id=? ORDER BY r.id",
            (meeting_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        c.close()
