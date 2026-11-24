import json
import uuid

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


def _old_previous(conn, uid, recorded_at, minutes, actions=()):
    pid = project_repo.ensure_project(conn, "项目A")
    mid = meeting_repo.create(
        conn, uid=uid, title=uid, project_id=pid,
        recorded_at=recorded_at, audio_filename=f"{uid}.m4a", status="done")
    meeting_repo.update_fields(conn, mid,
                               minutes=json.dumps(minutes, ensure_ascii=False))
    action_repo.replace(conn, mid, list(actions))
    return pid, mid


def _current_with_options(conn, pid, minutes, options):
    uid = "cur-" + uuid.uuid4().hex[:8]
    mid = meeting_repo.create(
        conn, uid=uid, title="本次会议", project_id=pid,
        recorded_at="2026-11-21 10:00:00", audio_filename=f"{uid}.m4a",
        status="relating")
    meeting = meeting_repo.get_by_id(conn, mid)
    return relations.build_relations(conn, meeting, minutes, options)


def test_time_window_limits_history(conn):
    pid, mid = _old_previous(conn, "old", "2025-01-01 10:00:00",
                             {"topics": [{"title": "预算讨论"}]})
    current = {"topics": [{"title": "预算讨论"}], "actions": []}
    assert _current_with_options(conn, pid, current,
                                 {"window_days": 30}) == []
    unlimited = _current_with_options(conn, pid, current, {"window_days": 0})
    assert [r["target_id"] for r in unlimited] == [mid]


def test_keyword_hint_matches_synonyms(conn):
    pid, mid = _old_previous(conn, "old", "2026-11-01 10:00:00",
                             {"topics": [{"title": "预算讨论"}]})
    current = {"topics": [{"title": "费用控制"}], "actions": []}
    assert _current_with_options(conn, pid, current, {"window_days": 30}) == []
    result = _current_with_options(conn, pid, current, {
        "window_days": 30, "hint": "预算, 费用"})
    assert [r["target_id"] for r in result] == [mid]
    assert "关键词" in result[0]["detail"]


def test_keyword_pulls_older_meeting_beyond_recent_limit(conn):
    pid, _ = _old_previous(conn, "recent", "2026-11-10 10:00:00",
                           {"topics": [{"title": "人员安排"}]})
    _, target = _old_previous(conn, "older", "2026-11-01 10:00:00",
                              {"topics": [{"title": "交付排期"}]})
    current = {"topics": [{"title": "上线时间"}], "actions": []}
    options = {"window_days": 180, "max_previous": 1, "hint": "交付, 上线"}
    result = _current_with_options(conn, pid, current, options)
    assert [r["target_id"] for r in result] == [target]


def test_relations_can_be_disabled(conn):
    pid, _ = _old_previous(conn, "old", "2026-11-01 10:00:00",
                           {"topics": [{"title": "预算讨论"}]})
    current = {"topics": [{"title": "预算讨论"}], "actions": []}
    assert _current_with_options(conn, pid, current, {"enabled": False}) == []
