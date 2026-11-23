from fastapi.testclient import TestClient

from app.main import create_app
from app.storage import db, meeting_repo, project_repo


def _client(cfg, username="admin", password="test-pass"):
    client = TestClient(create_app(cfg, start_threads=False))
    client.post("/login", data={"username": username, "password": password})
    return client


def test_member_is_forbidden_from_admin(cfg):
    admin = _client(cfg)
    resp = admin.post("/api/admin/users", json={
        "username": "member1", "display_name": "成员一",
        "password": "member-pass", "role": "member"})
    assert resp.status_code == 200

    member = _client(cfg, "member1", "member-pass")
    assert member.get("/").status_code == 200
    assert member.get("/admin").status_code == 403
    assert member.get("/api/admin/settings").status_code == 403
    assert member.get("/api/admin/users/template.csv").status_code == 403
    assert member.post("/api/admin/users/batch",
                       json={"items": []}).status_code == 403
    assert member.get("/api/meetings").status_code == 200


def test_batch_import_users(cfg):
    admin = _client(cfg)
    template = admin.get("/api/admin/users/template.csv")
    assert template.status_code == 200
    assert "username,display_name,password,role" in template.text

    resp = admin.post("/api/admin/users/batch", json={"items": [
        {"username": "batch1", "display_name": "批量一",
         "password": "batch-pass", "role": "member"},
        {"username": "batch2", "display_name": "批量二",
         "password": "batch-pass", "role": "member"},
        {"username": "admin", "display_name": "重复管理员",
         "password": "batch-pass", "role": "member"},
        {"username": "bad name", "password": "x", "role": "member"},
    ]})
    assert resp.status_code == 200
    data = resp.json()
    assert data["created"] == 2
    assert len(data["failed"]) == 2
    users = admin.get("/api/admin/users").json()["items"]
    assert {"batch1", "batch2"} <= {u["username"] for u in users}


def test_member_cannot_retry_or_manage_meeting(cfg):
    admin = _client(cfg)
    admin.post("/api/admin/users", json={
        "username": "member2", "display_name": "成员二",
        "password": "member-pass", "role": "member"})
    conn = db.connect(cfg.db_path)
    try:
        pid = project_repo.ensure_project(conn, "项目A")
        mid = meeting_repo.create(
            conn, uid="member-failed", title="成员不可操作",
            project_id=pid, recorded_at="2026-11-23 09:00:00",
            audio_filename="member-failed__a.m4a", status="failed")
        meeting_repo.update_fields(
            conn, mid, error_code="asr_unavailable",
            error_msg="FunASR 识别失败")
    finally:
        conn.close()

    member = _client(cfg, "member2", "member-pass")
    html = member.get("/m/member-failed").text
    assert "处理失败" in html
    assert "需要管理员处理" in html
    assert "重新生成纪要" not in html
    assert "标记结案" not in html
    assert "重试处理" not in html
    assert member.post("/api/meetings/member-failed/retry").status_code == 403
    assert member.post(
        "/api/admin/meetings/member-failed/regenerate").status_code == 403


def test_cannot_remove_last_admin(cfg):
    admin = _client(cfg)
    users = admin.get("/api/admin/users").json()
    me = next(u for u in users["items"] if u["username"] == "admin")
    assert admin.put(f"/api/admin/users/{me['id']}",
                     json={"role": "member"}).status_code == 400
    assert admin.delete(f"/api/admin/users/{me['id']}").status_code == 400


def test_change_password_invalidates_session(cfg):
    admin = _client(cfg)
    resp = admin.post("/api/admin/password", json={
        "old_password": "test-pass", "new_password": "new-pass-123"})
    assert resp.status_code == 200
    assert admin.get("/api/meetings").status_code == 401

    fresh = _client(cfg, "admin", "new-pass-123")
    assert fresh.get("/api/meetings").status_code == 200
