from fastapi.testclient import TestClient

from app.main import create_app


def test_healthz_needs_no_login(cfg):
    app = create_app(cfg, start_threads=False)
    with TestClient(app) as client:
        assert client.get("/healthz").json() == {"ok": True}


def test_root_redirects_to_login(cfg):
    app = create_app(cfg, start_threads=False)
    with TestClient(app) as client:
        resp = client.get("/", follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["location"] == "/login"


def test_api_returns_401_json(cfg):
    app = create_app(cfg, start_threads=False)
    with TestClient(app) as client:
        resp = client.get("/api/meetings")
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "unauthorized"


def test_login_success_and_logout(cfg):
    app = create_app(cfg, start_threads=False)
    with TestClient(app) as client:
        bad = client.post("/login", data={"password": "wrong"})
        assert bad.status_code == 401
        ok = client.post("/login", data={"password": "test-pass"}, follow_redirects=False)
        assert ok.status_code == 302
        assert client.get("/").status_code == 200
        client.post("/logout", follow_redirects=False)
        assert client.get("/api/meetings").status_code == 401


def test_login_rate_limited(cfg):
    app = create_app(cfg, start_threads=False)
    with TestClient(app) as client:
        codes = [client.post("/login", data={"password": "x"}).status_code
                 for _ in range(6)]
        assert codes[-1] == 429


def test_logging_writes_json_line(cfg):
    from app.core.logging import log_event, setup_logging
    setup_logging(cfg.log_dir)
    log_event("info", "test_event", uid="u1")
    text = (cfg.log_dir / "app.log").read_text(encoding="utf-8")
    assert "test_event" in text
    assert "u1" in text
