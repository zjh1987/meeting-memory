import json
from datetime import datetime

from fastapi.testclient import TestClient

from app.main import create_app
from app.storage import action_repo, db, meeting_repo, project_repo


def _client(cfg):
    client = TestClient(create_app(cfg, start_threads=False))
    client.post("/login", data={"username": "admin", "password": "test-pass"})
    return client


def _meeting(conn, uid, title, recorded_at, status="done", minutes=None):
    pid = project_repo.ensure_project(conn, "项目A")
    mid = meeting_repo.create(
        conn, uid=uid, title=title, project_id=pid,
        recorded_at=recorded_at, audio_filename=f"{uid}__a.m4a",
        status=status)
    meeting_repo.update_fields(conn, mid, duration_sec=600)
    if minutes:
        meeting_repo.update_fields(conn, mid, minutes=json.dumps(
            minutes, ensure_ascii=False))
    return mid


def test_dashboard_shows_stats_and_latest_minutes(cfg):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = db.connect(cfg.db_path)
    try:
        mid = _meeting(conn, "u1", "最近一次会议", now, minutes={
            "summary": "本次会议确认了数据同步方案与下周计划。",
            "topics": [], "decisions": [], "actions": [], "open_issues": [],
            "people": [],
        })
        action_repo.replace(conn, mid, [{
            "owner": "张敏", "task": "整理问题清单", "due": "周五",
            "quote": "我下周把问题清单整理出来", "segment_ids": [0]}])
    finally:
        conn.close()
    client = _client(cfg)
    html = client.get("/").text
    assert "工作概览" in html
    assert "会议总数" in html
    assert "本次会议确认了数据同步方案" in html
    assert "待跟进事项" not in html
    assert "待办事项" not in html
    assert "整理问题清单" not in html


def test_meeting_list_groups_by_month(cfg):
    conn = db.connect(cfg.db_path)
    try:
        _meeting(conn, "u2", "十月会议", "2026-10-05 10:00:00")
        _meeting(conn, "u3", "十一月会议", "2026-11-06 10:00:00")
    finally:
        conn.close()
    client = _client(cfg)
    html = client.get("/meetings").text
    assert "2026年10月" in html
    assert "2026年11月" in html
    assert "十月会议" in html


def test_upload_page_shows_ingest_path(cfg):
    client = _client(cfg)
    html = client.get("/upload").text
    assert "设备自动上传目录" in html
    assert str(cfg.inbox_dir) in html
    assert "离线录音补传" in html
