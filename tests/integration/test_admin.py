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
    client.post("/login", data={"password": "test-pass"})
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
        "sections": ["summary", "actions"], "hint": "重点提炼下周计划"})
    assert resp.status_code == 200
    keys = {t["key"] for t in client.get("/api/admin/templates").json()["items"]}
    assert {"standard", "weekly"} <= keys

    resp = client.post("/api/admin/templates", json={
        "key": "bad key", "name": "x", "sections": ["summary"], "hint": ""})
    assert resp.status_code == 400


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
