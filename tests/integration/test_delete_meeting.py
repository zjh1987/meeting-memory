import importlib.util
from pathlib import Path

from app.pipeline import archive
from app.storage import db, meeting_repo, project_repo

ROOT = Path(__file__).resolve().parents[2]


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "delete_meeting", ROOT / "deploy" / "delete_meeting.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_delete_meeting_removes_db_files_and_archive(cfg, conn):
    pid = project_repo.ensure_project(conn, "项目A")
    meeting_repo.create(
        conn, uid="u1", title="待删会议", project_id=pid,
        recorded_at="2026-11-21 10:00:00", audio_filename="u1__待删会议.m4a",
        status="done")
    meeting = meeting_repo.get_by_uid(conn, "u1")
    (cfg.archive_dir / meeting["audio_filename"]).write_bytes(b"audio")
    archive.write_meeting(cfg, meeting, "<html>待删</html>")
    archive.refresh_indices(cfg)

    module = _load_module()
    assert module.delete(cfg, "u1") == 0
    assert meeting_repo.get_by_uid(conn, "u1") is None
    assert not (cfg.archive_dir / meeting["audio_filename"]).exists()
    assert not (cfg.site_dir / "2026" / "11" / "21" / "u1").exists()
