import json

from app.core import similarity
from app.pipeline import relations
from app.storage import action_repo, meeting_repo, project_repo


def test_jaccard_basic():
    assert similarity.jaccard("数据同步问题", "数据同步问题") == 1.0
    assert similarity.jaccard("数据同步问题", "预算待定") == 0.0
    assert 0 < similarity.jaccard("整理问题清单", "问题清单整理") < 1


def _previous(conn, minutes, actions):
    pid = project_repo.ensure_project(conn, "项目A")
    mid = meeting_repo.create(
        conn, uid="prev", title="上次会议", project_id=pid,
        recorded_at="2026-11-20 10:00:00", audio_filename="prev.m4a",
        status="done")
    meeting_repo.update_fields(conn, mid,
                               minutes=json.dumps(minutes, ensure_ascii=False))
    action_repo.replace(conn, mid, actions)
    return pid, mid


def _current(conn, pid, minutes):
    mid = meeting_repo.create(
        conn, uid="cur", title="本次会议", project_id=pid,
        recorded_at="2026-11-21 10:00:00", audio_filename="cur.m4a",
        status="relating")
    meeting = meeting_repo.get_by_id(conn, mid)
    return relations.build_relations(conn, meeting, minutes)


def test_pending_carryover_is_reported(conn):
    prev_minutes = {"topics": [{"title": "预算讨论"}]}
    pid, _ = _previous(conn, prev_minutes, [
        {"owner": "张敏", "task": "整理数据同步问题清单", "due": "下周",
         "quote": "我下周先把问题清单整理出来", "segment_ids": [1]},
    ])
    current_minutes = {
        "topics": [{"title": "人员安排"}],
        "actions": [{"owner": "李工", "task": "申请测试资源", "due": "",
                     "quote": "需要提前申请资源", "segment_ids": [2]}],
    }
    result = _current(conn, pid, current_minutes)
    kinds = [r["kind"] for r in result]
    assert "pending_carryover" in kinds
    card = next(r for r in result if r["kind"] == "pending_carryover")
    assert "1 条待办" in card["detail"]
    assert card["quote"] == "整理数据同步问题清单"


def test_matched_action_suppresses_carryover(conn):
    pid, _ = _previous(conn, {"topics": []}, [
        {"owner": "张敏", "task": "整理数据同步问题清单", "due": "下周",
         "quote": "我下周先把问题清单整理出来", "segment_ids": [1]},
    ])
    current_minutes = {
        "topics": [],
        "actions": [{"owner": "张敏", "task": "整理数据同步问题清单", "due": "本周",
                     "quote": "我先把清单整理出来", "segment_ids": [3]}],
    }
    assert _current(conn, pid, current_minutes) == []


def test_repeat_topic_is_reported(conn):
    pid, _ = _previous(conn, {"topics": [{"title": "数据同步问题"}]}, [])
    current_minutes = {"topics": [{"title": "数据同步问题"}], "actions": []}
    result = _current(conn, pid, current_minutes)
    assert [r["kind"] for r in result] == ["repeat_topic"]
    assert result[0]["quote"] == "数据同步问题"
