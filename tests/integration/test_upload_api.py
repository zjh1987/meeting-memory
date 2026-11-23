from fastapi.testclient import TestClient

from app.main import create_app
from app.storage import db, meeting_repo


def _client(cfg):
    app = create_app(cfg, start_threads=False)
    client = TestClient(app)
    client.__enter__()
    client.post("/login", data={"username": "admin", "password": "test-pass"})
    return client


def test_upload_creates_uploading_meeting(cfg):
    client = _client(cfg)
    try:
        resp = client.post(
            "/api/meetings",
            files={"file": ("a.m4a", b"fake-bytes", "audio/mp4")},
            data={"title": "测试会", "project_name": "项目A"},
        )
        assert resp.status_code == 200
        uid = resp.json()["uid"]
        conn = db.connect(cfg.db_path)
        try:
            m = meeting_repo.get_by_uid(conn, uid)
        finally:
            conn.close()
        assert m["status"] == "uploading"
        assert m["title"] == "测试会"
        assert (cfg.inbox_dir / m["audio_filename"]).exists()
        assert not list(cfg.inbox_dir.glob("*.part"))
    finally:
        client.__exit__(None, None, None)


def test_upload_rejects_bad_suffix_and_missing_project(cfg):
    client = _client(cfg)
    try:
        bad = client.post("/api/meetings",
                          files={"file": ("a.txt", b"x", "text/plain")},
                          data={"project_name": "项目A"})
        assert bad.status_code == 400
        no_project = client.post("/api/meetings",
                                 files={"file": ("a.m4a", b"x", "audio/mp4")})
        assert no_project.status_code == 400
        assert no_project.json()["error"]["code"] == "upload_invalid"
    finally:
        client.__exit__(None, None, None)


def test_upload_rejects_empty_file(cfg):
    client = _client(cfg)
    try:
        resp = client.post(
            "/api/meetings",
            files={"file": ("a.m4a", b"", "audio/mp4")},
            data={"title": "空文件", "project_name": "项目A"},
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "upload_invalid"
        assert not list(cfg.inbox_dir.iterdir())
    finally:
        client.__exit__(None, None, None)


def test_upload_long_chinese_title_filename_within_limit(cfg):
    client = _client(cfg)
    try:
        resp = client.post(
            "/api/meetings",
            files={"file": ("a.m4a", b"fake-bytes", "audio/mp4")},
            data={"title": "长" * 100, "project_name": "项目A"},
        )
        assert resp.status_code == 200
        audio = [p for p in cfg.inbox_dir.iterdir() if p.suffix.lower() == ".m4a"]
        assert len(audio) == 1
        assert len(audio[0].name.encode("utf-8")) <= 255
    finally:
        client.__exit__(None, None, None)


def test_upload_accepts_recorded_at(cfg):
    client = _client(cfg)
    try:
        resp = client.post(
            "/api/meetings",
            files={"file": ("a.wav", b"fake-bytes", "audio/wav")},
            data={"title": "补传会议", "project_name": "项目A",
                  "recorded_at": "2026-11-20 09:30:00"},
        )
        assert resp.status_code == 200
        uid = resp.json()["uid"]
        conn = db.connect(cfg.db_path)
        try:
            m = meeting_repo.get_by_uid(conn, uid)
        finally:
            conn.close()
        assert m["recorded_at"] == "2026-11-20 09:30:00"
    finally:
        client.__exit__(None, None, None)


def test_upload_rejects_invalid_recorded_at(cfg):
    client = _client(cfg)
    try:
        resp = client.post(
            "/api/meetings",
            files={"file": ("a.wav", b"fake-bytes", "audio/wav")},
            data={"project_name": "项目A", "recorded_at": "2026/11/20"},
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "upload_invalid"
        assert not list(cfg.inbox_dir.iterdir())
    finally:
        client.__exit__(None, None, None)


def test_projects_endpoint(cfg):
    client = _client(cfg)
    try:
        resp = client.get("/api/projects")
        names = [p["name"] for p in resp.json()["items"]]
        assert "未归类" in names
    finally:
        client.__exit__(None, None, None)
