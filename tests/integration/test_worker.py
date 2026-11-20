import json
from datetime import datetime, timedelta

from app.pipeline import maintainer, worker
from app.providers.errors import ProviderError
from app.storage import action_repo, db, meeting_repo, project_repo


def _pending(cfg):
    conn = db.connect(cfg.db_path)
    try:
        pid = project_repo.ensure_project(conn, "项目A")
        mid = meeting_repo.create(
            conn, uid="u1", title="测试会", project_id=pid,
            recorded_at="2026-11-21 10:00:00", audio_filename="u1__测试会.m4a")
    finally:
        conn.close()
    (cfg.ready_dir / "u1__测试会.m4a").write_bytes(b"audio")
    return mid


def test_process_once_completes_pipeline(cfg):
    mid = _pending(cfg)
    assert worker.process_once(cfg) is True
    conn = db.connect(cfg.db_path)
    try:
        m = meeting_repo.get_by_id(conn, mid)
        assert m["status"] == "done"
        assert json.loads(m["minutes"])["summary"]
        assert action_repo.list_for(conn, mid)
    finally:
        conn.close()
    assert (cfg.archive_dir / "u1__测试会.m4a").exists()
    assert list(cfg.site_dir.rglob("index.html"))


def test_process_once_returns_false_when_empty(cfg):
    assert worker.process_once(cfg) is False


def test_transient_error_is_requeued(cfg, monkeypatch):
    mid = _pending(cfg)

    def boom(cfg_arg, meeting):
        raise ProviderError("asr_timeout", "超时", transient=True)

    monkeypatch.setattr("app.pipeline.transcribe.run", boom)
    assert worker.process_once(cfg) is True
    conn = db.connect(cfg.db_path)
    try:
        m = meeting_repo.get_by_id(conn, mid)
        assert m["status"] == "pending"
        assert m["retry_count"] == 1
        assert m["next_retry_at"] is not None
        assert m["error_code"] == "asr_timeout"
    finally:
        conn.close()


def test_reclaim_zombies(cfg):
    mid = _pending(cfg)
    conn = db.connect(cfg.db_path)
    try:
        old = (datetime.now() - timedelta(seconds=600)).strftime("%Y-%m-%d %H:%M:%S")
        meeting_repo.update_fields(conn, mid, status="transcribing",
                                   started_at=old, heartbeat_at=old)
    finally:
        conn.close()
    assert maintainer.reclaim_zombies(cfg) == 1
    conn = db.connect(cfg.db_path)
    try:
        m = meeting_repo.get_by_id(conn, mid)
        assert m["status"] == "pending"
        assert m["retry_count"] == 1
    finally:
        conn.close()
