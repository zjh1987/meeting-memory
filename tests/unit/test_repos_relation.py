from app.storage import action_repo, meeting_repo, project_repo, relation_repo


def _meeting(conn, uid="u1"):
    pid = project_repo.ensure_project(conn, "项目A")
    return meeting_repo.create(
        conn, uid=uid, title="会", project_id=pid,
        recorded_at="2026-11-21 10:00:00", audio_filename=f"{uid}.m4a",
    )


def test_replace_and_read_actions(conn):
    mid = _meeting(conn)
    action_repo.replace(conn, mid, [
        {"owner": "张敏", "task": "整理问题清单", "due": "下周",
         "quote": "我下周先把问题清单整理出来", "segment_ids": [3]},
    ])
    rows = action_repo.list_for(conn, mid)
    assert len(rows) == 1
    assert rows[0]["segment_ids"] == [3]
    assert rows[0]["status"] == "open"


def test_open_for_only_returns_open(conn):
    mid = _meeting(conn)
    action_repo.replace(conn, mid, [
        {"owner": "A", "task": "t1", "due": "", "quote": "q1", "segment_ids": [0]},
        {"owner": "B", "task": "t2", "due": "", "quote": "q2", "segment_ids": [1]},
    ])
    conn.execute("UPDATE action_item SET status='done' WHERE task='t2'")
    rows = action_repo.open_for(conn, mid)
    assert [r["task"] for r in rows] == ["t1"]


def test_relations_join_target_meeting(conn):
    a = _meeting(conn, uid="u1")
    b = _meeting(conn, uid="u2")
    relation_repo.replace(conn, b, [
        {"target_id": a, "kind": "repeat_topic", "detail": "议题重复", "quote": "预算"},
    ])
    rows = relation_repo.list_for(conn, b)
    assert rows[0]["target_uid"] == "u1"
    assert rows[0]["target_title"] == "会"
