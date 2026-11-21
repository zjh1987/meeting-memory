from fastapi.testclient import TestClient

from app.main import create_app
from app.pipeline import harvester, worker
from app.storage import db, meeting_repo, relation_repo


def test_upload_to_archive_and_relation(cfg):
    app = create_app(cfg, start_threads=False)
    with TestClient(app) as client:
        client.post("/login", data={"username": "admin", "password": "test-pass"})

        first = client.post(
            "/api/meetings",
            files={"file": ("一季会.m4a", b"audio-1", "audio/mp4")},
            data={"title": "一季会", "project_name": "项目A"},
        ).json()["uid"]
        assert harvester.harvest_once(cfg) == 1
        assert worker.process_once(cfg) is True

        conn = db.connect(cfg.db_path)
        try:
            m1 = meeting_repo.get_by_uid(conn, first)
            assert m1["status"] == "done"
        finally:
            conn.close()

        day = m1["recorded_at"][:10].split("-")
        archive_file = cfg.site_dir.joinpath(*day, first, "index.html")
        assert archive_file.exists()
        assert "本次会议" in archive_file.read_text(encoding="utf-8")

        second = client.post(
            "/api/meetings",
            files={"file": ("二季会.m4a", b"audio-2", "audio/mp4")},
            data={"title": "二季会", "project_name": "项目A"},
        ).json()["uid"]
        assert harvester.harvest_once(cfg) == 1
        assert worker.process_once(cfg) is True

        conn = db.connect(cfg.db_path)
        try:
            m2 = meeting_repo.get_by_uid(conn, second)
            assert m2["status"] == "done"
            rels = relation_repo.list_for(conn, m2["id"])
            assert rels, "第二场同项目会议应产生关联"
            assert all(r["quote"] for r in rels)
        finally:
            conn.close()

        detail = client.get(f"/m/{second}").text
        assert "与以往会议的关联" in detail
