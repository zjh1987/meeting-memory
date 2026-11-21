from fastapi.testclient import TestClient

from app.main import create_app


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
    assert member.get("/api/meetings").status_code == 200


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
