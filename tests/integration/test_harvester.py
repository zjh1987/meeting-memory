import os
from datetime import datetime

from app.pipeline import harvester
from app.pipeline.harvester import harvest_once
from app.services import settings as settings_service
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


def test_missing_template_uses_first_template(cfg):
    conn = db.connect(cfg.db_path)
    try:
        assert settings_service.move_template(conn, "standard", "down")[0]["key"] == "weekly"
    finally:
        conn.close()
    (cfg.inbox_dir / "u3__设备录音.m4a").write_bytes(b"audio")
    assert harvest_once(cfg) == 1
    conn = db.connect(cfg.db_path)
    try:
        assert meeting_repo.get_by_uid(conn, "u3")["template_key"] == "weekly"
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


def test_unsafe_uid_gets_generated_uid(cfg):
    assert harvester._safe_uid("..") is None
    assert harvester._safe_uid("../evil") is None
    assert harvester._safe_uid("20261121-100000-abcd") == "20261121-100000-abcd"

    path = cfg.inbox_dir / "bad uid__会议.m4a"
    path.write_bytes(b"audio")
    (cfg.inbox_dir / "bad uid__会议.json").write_text(
        '{"project": "项目A", "recorded_at": "2026-11-21 09:00:00"}',
        encoding="utf-8")
    assert harvest_once(cfg) == 1
    assert not path.exists()
    conn = db.connect(cfg.db_path)
    try:
        row = conn.execute("SELECT uid, title FROM meeting").fetchone()
        assert row["uid"] != "bad uid"
        assert row["title"] == "会议"
    finally:
        conn.close()


def test_invalid_recorded_at_falls_back_to_mtime(cfg):
    path = cfg.inbox_dir / "u1__会议.m4a"
    path.write_bytes(b"audio")
    (cfg.inbox_dir / "u1__会议.json").write_text(
        '{"recorded_at": "../../../../etc"}', encoding="utf-8")
    stamp = datetime(2026, 11, 20, 8, 0, 0).timestamp()
    os.utime(path, (stamp, stamp))

    assert harvest_once(cfg) == 1
    conn = db.connect(cfg.db_path)
    try:
        m = meeting_repo.get_by_uid(conn, "u1")
        assert m["recorded_at"] == "2026-11-20 08:00:00"
    finally:
        conn.close()


def test_db_failure_keeps_file_and_meta(cfg, monkeypatch):
    path = cfg.inbox_dir / "u1__会议.m4a"
    path.write_bytes(b"audio")
    meta = cfg.inbox_dir / "u1__会议.json"
    meta.write_text('{"project": "项目A"}', encoding="utf-8")

    def boom(*args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(harvester.meeting_repo, "create", boom)
    assert harvest_once(cfg) == 0
    assert path.exists() and meta.exists()
    assert not list(cfg.ready_dir.iterdir())
    conn = db.connect(cfg.db_path)
    try:
        assert conn.execute("SELECT COUNT(*) AS n FROM meeting").fetchone()["n"] == 0
    finally:
        conn.close()


def test_update_failure_moves_file_back(cfg, monkeypatch):
    path = cfg.inbox_dir / "u1__会议.m4a"
    path.write_bytes(b"audio")
    meta = cfg.inbox_dir / "u1__会议.json"
    meta.write_text('{"project": "项目A"}', encoding="utf-8")

    def boom(*args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(harvester.meeting_repo, "update_fields", boom)
    assert harvest_once(cfg) == 0
    assert path.exists() and meta.exists()
    assert not list(cfg.ready_dir.iterdir())
    conn = db.connect(cfg.db_path)
    try:
        m = meeting_repo.get_by_uid(conn, "u1")
        assert m["status"] == "uploading"
    finally:
        conn.close()
