import json
from dataclasses import replace

from fastapi.testclient import TestClient

from app.main import create_app
from app.pipeline import transcribe
from app.providers.errors import ProviderError
from app.storage import db, meeting_repo, project_repo, relation_repo
from app.services import settings as settings_service


def _client(cfg):
    app = create_app(cfg, start_threads=False)
    client = TestClient(app)
    client.post("/login", data={"username": "admin", "password": "test-pass"})
    return client


def test_admin_settings_and_secrets(cfg):
    conn = db.connect(cfg.db_path)
    try:
        settings_service.save_llm(conn, {
            "provider": "openai", "base_url": "http://127.0.0.1:9000/v1",
            "model": "local-model", "api_key": "sk-secret-123456", "temperature": 0.2})
    finally:
        conn.close()
    client = _client(cfg)
    data = client.get("/api/admin/settings").json()
    assert data["llm"]["model"] == "local-model"
    assert data["llm"]["has_key"] is True
    assert "sk-secret-123456" not in json.dumps(data)
    assert data["llm"]["masked_key"].startswith("sk-")
    assert {m["key"] for m in data["asr"]["models"]} == {"asr", "vad", "punc", "spk"}


def test_admin_hotwords_and_templates(cfg):
    client = _client(cfg)
    resp = client.put("/api/admin/hotwords",
                      json={"items": ["张敏", "数据同步", "张敏", ""]})
    assert resp.status_code == 200
    assert resp.json()["count"] == 2
    assert cfg.hotword_file.read_text(encoding="utf-8").split() == ["张敏", "数据同步"]

    resp = client.post("/api/admin/templates", json={
        "key": "weekly", "name": "周会",
        "scene": "周会", "description": "固定周会",
        "sections": ["summary", "actions"], "hint": "重点提炼下周计划",
        "custom_sections": [{"key": "risks", "title": "风险与依赖",
                             "instruction": "列出风险"}]})
    assert resp.status_code == 200
    saved = resp.json()["template"]
    assert saved["custom_sections"][0]["title"] == "风险与依赖"
    keys = {t["key"] for t in client.get("/api/admin/templates").json()["items"]}
    assert {"standard", "weekly"} <= keys

    resp = client.post("/api/admin/templates", json={
        "key": "bad key", "name": "x", "sections": ["summary"], "hint": ""})
    assert resp.status_code == 400


def test_template_order_and_default_upload(cfg):
    client = _client(cfg)
    items = client.get("/api/admin/templates").json()["items"]
    assert [item["key"] for item in items][:2] == ["standard", "weekly"]

    created = client.post("/api/admin/templates", json={
        "key": "custom-order", "name": "自定义排序",
        "scene": "自定义", "description": "测试排序",
        "sections": ["summary"], "hint": "测试"})
    assert created.status_code == 200
    assert created.json()["template"]["sort_order"] > 0

    moved = client.post("/api/admin/templates/standard/move",
                        json={"direction": "down"})
    assert moved.status_code == 200
    assert moved.json()["items"][0]["key"] == "weekly"

    upload = client.post(
        "/api/meetings",
        files={"file": ("a.wav", b"fake-audio", "audio/wav")},
        data={"project_name": "项目A"},
    )
    assert upload.status_code == 200
    conn = db.connect(cfg.db_path)
    try:
        row = meeting_repo.get_by_uid(conn, upload.json()["uid"])
    finally:
        conn.close()
    assert row["template_key"] == "weekly"


def test_close_meeting_excluded_from_relations(cfg):
    conn = db.connect(cfg.db_path)
    try:
        pid = project_repo.ensure_project(conn, "项目A")
        first = meeting_repo.create(
            conn, uid="u1", title="一", project_id=pid,
            recorded_at="2026-11-21 10:00:00", audio_filename="u1__a.m4a",
            status="done")
        second = meeting_repo.create(
            conn, uid="u2", title="二", project_id=pid,
            recorded_at="2026-11-21 11:00:00", audio_filename="u2__b.m4a",
            status="done")
    finally:
        conn.close()
    client = _client(cfg)
    assert client.post("/api/admin/meetings/u1/close",
                       json={"closed": True}).status_code == 200
    conn = db.connect(cfg.db_path)
    try:
        previous = meeting_repo.previous_done(conn, pid, second + 1)
        assert [m["uid"] for m in previous] == ["u2"]
    finally:
        conn.close()


def test_relation_settings_roundtrip(cfg):
    client = _client(cfg)
    resp = client.post("/api/admin/relations", json={
        "enabled": True, "window_days": 90, "max_previous": 6,
        "topic_threshold": 0.55, "task_threshold": 0.45,
        "hint": "预算, 费用\n交付, 上线"})
    assert resp.status_code == 200
    saved = resp.json()["settings"]
    assert saved["window_days"] == 90
    assert saved["hint"].startswith("预算")
    settings = client.get("/api/admin/settings").json()
    assert settings["relations"]["max_previous"] == 6

    bad = client.post("/api/admin/relations", json={"window_days": 5000})
    assert bad.status_code == 400


def test_admin_project_management_and_reassign(cfg):
    client = _client(cfg)
    created = client.post("/api/admin/projects", json={"name": "项目甲"})
    assert created.status_code == 200
    pid = created.json()["project"]["id"]
    assert client.post("/api/admin/projects", json={"name": "项目甲"}).status_code == 400

    conn = db.connect(cfg.db_path)
    try:
        meeting_repo.create(
            conn, uid="p1", title="会议", project_id=pid,
            recorded_at="2026-11-21 10:00:00", audio_filename="p1.m4a",
            status="done")
    finally:
        conn.close()

    renamed = client.put(f"/api/admin/projects/{pid}", json={"name": "项目乙"})
    assert renamed.status_code == 200
    assert renamed.json()["project"]["name"] == "项目乙"
    items = {item["name"]: item
             for item in client.get("/api/admin/projects").json()["items"]}
    assert items["项目乙"]["meeting_count"] == 1

    target = client.post("/api/admin/projects", json={"name": "归集目标"})
    target_id = target.json()["project"]["id"]
    refused = client.delete(f"/api/admin/projects/{pid}")
    assert refused.status_code == 400
    moved = client.delete(f"/api/admin/projects/{pid}?move_to={target_id}")
    assert moved.status_code == 200
    assert moved.json()["moved"] == 1

    conn = db.connect(cfg.db_path)
    try:
        row = meeting_repo.get_by_uid(conn, "p1")
        assert row["project_id"] == target_id
    finally:
        conn.close()


def test_admin_can_move_single_meeting(cfg):
    client = _client(cfg)
    first = client.post("/api/admin/projects", json={"name": "甲"}).json()["project"]["id"]
    second = client.post("/api/admin/projects", json={"name": "乙"}).json()["project"]["id"]
    conn = db.connect(cfg.db_path)
    try:
        meeting_repo.create(
            conn, uid="m1", title="会议", project_id=first,
            recorded_at="2026-11-21 10:00:00", audio_filename="m1.m4a",
            status="done")
    finally:
        conn.close()
    resp = client.post("/api/admin/meetings/m1/project",
                       json={"project_id": second})
    assert resp.status_code == 200
    conn = db.connect(cfg.db_path)
    try:
        assert meeting_repo.get_by_uid(conn, "m1")["project_id"] == second
    finally:
        conn.close()


def test_app_release_upload_and_public_download(cfg):
    client = _client(cfg)
    resp = client.post(
        "/api/admin/app-apk",
        files={"file": ("app.apk", b"fake-apk", "application/vnd.android.package-archive")},
        data={"version_code": "4", "version_name": "1.0.3", "notes": "测试版本"})
    assert resp.status_code == 200
    release = resp.json()["release"]
    assert release["version_code"] == 4

    info = client.get("/api/app/android/latest").json()
    assert info["available"] is True
    assert info["url"].endswith(".apk")
    download = client.get(info["url"])
    assert download.status_code == 200
    assert download.content == b"fake-apk"

    anonymous = TestClient(create_app(cfg, start_threads=False))
    assert anonymous.get("/api/app/android/latest").status_code == 200


def test_static_archive_is_served_inside_app(cfg):
    (cfg.site_dir / "index.html").write_text("<html>归档首页</html>",
                                             encoding="utf-8")
    client = _client(cfg)
    resp = client.get("/site/index.html")
    assert resp.status_code == 200
    assert "归档首页" in resp.text


def test_duration_limit_rejects_before_asr(cfg, monkeypatch, tmp_path):
    audio = cfg.ready_dir / "u9__长会议.m4a"
    audio.write_bytes(b"audio")
    wav = tmp_path / "long.wav"
    wav.write_bytes(b"fake")
    monkeypatch.setattr("app.pipeline.media.to_wav", lambda src, dst: wav)
    monkeypatch.setattr("app.pipeline.media.wav_duration_sec", lambda path: 120.0)
    monkeypatch.setattr("app.providers.asr_funasr.FunAsrProvider.transcribe",
                        lambda self, path: [])
    long_cfg = replace(cfg, asr_backend="funasr", max_duration_min=1)
    meeting = {"audio_filename": audio.name}
    try:
        transcribe.run(long_cfg, meeting, {"backend": "funasr"}, 1)
    except ProviderError as exc:
        assert exc.code == "audio_too_long"
        assert "超过上限" in exc.message
    else:
        raise AssertionError("超长音频应被拒绝")
