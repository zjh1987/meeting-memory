from datetime import datetime

import pytest

from app.pipeline import archive
from app.storage import meeting_repo, project_repo


def test_write_meeting_page(cfg, conn):
    pid = project_repo.ensure_project(conn, "项目A")
    meeting_repo.create(
        conn, uid="20261121-100000-abcd", title="测试会", project_id=pid,
        recorded_at="2026-11-21 10:00:00", audio_filename="a.m4a", status="done")
    meeting = meeting_repo.get_by_uid(conn, "20261121-100000-abcd")
    target = archive.write_meeting(cfg, meeting, "<html>纪要</html>")
    assert target == cfg.site_dir / "2026" / "11" / "21" / "20261121-100000-abcd" / "index.html"
    assert "纪要" in target.read_text(encoding="utf-8")


def test_refresh_indices(cfg, conn):
    pid = project_repo.ensure_project(conn, "项目A")
    meeting_repo.create(
        conn, uid="u1", title="第一场", project_id=pid,
        recorded_at="2026-11-21 10:00:00", audio_filename="a.m4a", status="done")
    meeting_repo.create(
        conn, uid="u2", title="第二场", project_id=pid,
        recorded_at="2026-11-20 10:00:00", audio_filename="b.m4a", status="done")
    archive.refresh_indices(cfg)

    day_page = (cfg.site_dir / "2026" / "11" / "21" / "index.html").read_text(encoding="utf-8")
    assert "第一场" in day_page
    root = (cfg.site_dir / "index.html").read_text(encoding="utf-8")
    assert "2026-11-21" in root and "2026-11-20" in root


def test_invalid_recorded_at_falls_back_to_today(cfg):
    today = datetime.now()
    expected = cfg.site_dir.joinpath(today.strftime("%Y"), today.strftime("%m"),
                                     today.strftime("%d"))
    assert archive.day_dir(cfg, "../../../../etc") == expected
    assert archive.day_dir(cfg, "2026-13-99 10:00:00") == expected


def test_write_meeting_rejects_escape(cfg, conn):
    pid = project_repo.ensure_project(conn, "项目A")
    meeting_repo.create(
        conn, uid="../../../../outside", title="越界", project_id=pid,
        recorded_at="2026-11-21 10:00:00", audio_filename="a.m4a", status="done")
    meeting = meeting_repo.get_by_uid(conn, "../../../../outside")
    with pytest.raises(ValueError):
        archive.write_meeting(cfg, meeting, "<html>越界</html>")
    assert not (cfg.site_dir.parent / "outside").exists()


def test_refresh_indices_sanitizes_invalid_date(cfg, conn):
    pid = project_repo.ensure_project(conn, "项目A")
    meeting_repo.create(
        conn, uid="u1", title="坏日期", project_id=pid,
        recorded_at="../../../../etc", audio_filename="a.m4a", status="done")
    archive.refresh_indices(cfg)
    today = datetime.now().strftime("%Y-%m-%d")
    root = (cfg.site_dir / "index.html").read_text(encoding="utf-8")
    assert today in root
    assert not (cfg.site_dir.parent / "etc").exists()
