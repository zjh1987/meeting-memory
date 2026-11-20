from app.pipeline.harvester import harvest_once
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
