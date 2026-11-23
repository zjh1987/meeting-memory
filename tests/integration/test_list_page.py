from fastapi.testclient import TestClient

from app.main import create_app
from app.storage import db, meeting_repo, project_repo


def _seed(cfg):
    conn = db.connect(cfg.db_path)
    try:
        pid = project_repo.ensure_project(conn, "项目A")
        meeting_repo.create(
            conn, uid="20261121-100000-abcd", title="三季度进度会",
            project_id=pid, recorded_at="2026-11-21 10:00:00",
            audio_filename="a.m4a", status="pending")
    finally:
        conn.close()


def _client(cfg):
    client = TestClient(create_app(cfg, start_threads=False))
    client.__enter__()
    client.post("/login", data={"username": "admin", "password": "test-pass"})
    return client


def test_index_lists_meeting(cfg):
    _seed(cfg)
    client = _client(cfg)
    try:
        html = client.get("/meetings").text
        assert "三季度进度会" in html
        assert "项目A" in html
        assert "排队中" in html
    finally:
        client.__exit__(None, None, None)


def test_failed_meeting_error_visible_in_list(cfg):
    _seed(cfg)
    conn = db.connect(cfg.db_path)
    try:
        row = conn.execute(
            "SELECT id FROM meeting WHERE uid=?",
            ("20261121-100000-abcd",)).fetchone()
        meeting_repo.update_fields(
            conn, row["id"], status="failed", error_code="asr_unavailable",
            error_msg="FunASR 识别失败：Cannot interpret 'torch.float32' as a data type")
    finally:
        conn.close()
    client = _client(cfg)
    try:
        html = client.get("/meetings").text
        assert "查看原因并重试" in html
        assert "asr_unavailable" in html
        assert "torch.float32" in html
    finally:
        client.__exit__(None, None, None)


def test_status_endpoint(cfg):
    _seed(cfg)
    client = _client(cfg)
    try:
        data = client.get("/api/meetings/20261121-100000-abcd/status").json()
        assert data["status"] == "pending"
        assert data["status_label"] == "排队中"
        assert data["can_retry"] is False
    finally:
        client.__exit__(None, None, None)


def test_list_api_filters_by_project(cfg):
    _seed(cfg)
    client = _client(cfg)
    try:
        projects = client.get("/api/projects").json()["items"]
        pid = next(p["id"] for p in projects if p["name"] == "项目A")
        data = client.get(f"/api/meetings?project_id={pid}").json()
        assert data["total"] == 1
        assert data["items"][0]["uid"] == "20261121-100000-abcd"
    finally:
        client.__exit__(None, None, None)
