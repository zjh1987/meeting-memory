import os
from datetime import datetime, timedelta

from app.pipeline import maintainer
from app.storage import meeting_repo, project_repo


def test_warn_orphan_ready_only_reports_unknown_old_files(cfg, conn):
    pid = project_repo.ensure_project(conn, "项目A")
    meeting_repo.create(
        conn, uid="u1", title="已知", project_id=pid,
        recorded_at="2026-11-21 10:00:00", audio_filename="u1__已知.m4a",
        status="uploading")

    now = datetime.now()
    old = (now - timedelta(hours=48)).timestamp()
    known = cfg.ready_dir / "u1__已知.m4a"
    orphan = cfg.ready_dir / "u2__孤儿.m4a"
    fresh = cfg.ready_dir / "u3__新文件.m4a"
    for path in (known, orphan, fresh):
        path.write_bytes(b"audio")
    for path in (known, orphan):
        os.utime(path, (old, old))

    assert maintainer.warn_orphan_ready(cfg, now=now) == 1
    assert orphan.exists()
