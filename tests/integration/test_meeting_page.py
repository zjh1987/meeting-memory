import json

from fastapi.testclient import TestClient

from app.main import create_app
from app.storage import action_repo, db, meeting_repo, project_repo


def _seed(cfg, status="done"):
    conn = db.connect(cfg.db_path)
    try:
        pid = project_repo.ensure_project(conn, "项目A")
        mid = meeting_repo.create(
            conn, uid="20261121-100000-abcd", title="三季度进度会",
            project_id=pid, recorded_at="2026-11-21 10:00:00",
            audio_filename="a.m4a", status=status)
        meeting_repo.update_fields(
            conn, mid,
            transcript=json.dumps([{"idx": 0, "start": 0, "end": 4,
                                    "speaker": "王总", "text": "今天过一下进度。"}],
                                  ensure_ascii=False),
            minutes=json.dumps({
                "summary": "本次会议讨论了进度。",
                "topics": [{"title": "进度", "points": [], "segment_ids": [0]}],
                "decisions": [], "actions": [], "open_issues": [], "people": [],
            }, ensure_ascii=False))
        action_repo.replace(conn, mid, [])
    finally:
        conn.close()
    return mid


def _client(cfg):
    client = TestClient(create_app(cfg, start_threads=False))
    client.__enter__()
    client.post("/login", data={"username": "admin", "password": "test-pass"})
    return client


def test_meeting_page_renders_minutes_and_transcript(cfg):
    _seed(cfg)
    client = _client(cfg)
    try:
        html = client.get("/m/20261121-100000-abcd").text
        assert "本次会议讨论了进度。" in html
        assert "今天过一下进度。" in html
        assert "返回列表" in html
    finally:
        client.__exit__(None, None, None)


def test_meeting_page_404(cfg):
    client = _client(cfg)
    try:
        assert client.get("/m/not-exists").status_code == 404
    finally:
        client.__exit__(None, None, None)


def test_failed_meeting_shows_actionable_reason(cfg):
    mid = _seed(cfg, status="failed")
    conn = db.connect(cfg.db_path)
    try:
        meeting_repo.update_fields(
            conn, mid, error_code="asr_unavailable",
            error_msg="FunASR 识别失败：Cannot interpret 'torch.float32' as a data type")
    finally:
        conn.close()
    client = _client(cfg)
    try:
        html = client.get("/m/20261121-100000-abcd").text
        assert "处理失败" in html
        assert "说话人分离" in html
        assert "技术详情" in html
        assert "torch.float32" in html
        assert "页面每 3 秒自动刷新" not in html
        assert "setTimeout(() => location.reload(), 3000)" not in html
    finally:
        client.__exit__(None, None, None)


def test_retry_moves_failed_to_pending(cfg):
    _seed(cfg, status="failed")
    client = _client(cfg)
    try:
        resp = client.post("/api/meetings/20261121-100000-abcd/retry")
        assert resp.status_code == 200
        assert resp.json()["status"] == "pending"
    finally:
        client.__exit__(None, None, None)


def test_retry_rejects_completed_meeting(cfg):
    _seed(cfg, status="done")
    client = _client(cfg)
    try:
        resp = client.post("/api/meetings/20261121-100000-abcd/retry")
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "invalid_state"
    finally:
        client.__exit__(None, None, None)
