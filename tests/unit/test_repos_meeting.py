from app.storage import meeting_repo, project_repo


def _create(conn, uid="20261121-100000-abcd", title="测试会", project="项目A", status="pending"):
    pid = project_repo.ensure_project(conn, project)
    return meeting_repo.create(
        conn, uid=uid, title=title, project_id=pid,
        recorded_at="2026-11-21 10:00:00", audio_filename=f"{uid}__{title}.m4a",
        audio_size=1024, status=status,
    )


def test_ensure_project_reuses_existing(conn):
    a = project_repo.ensure_project(conn, "项目A")
    b = project_repo.ensure_project(conn, "项目A")
    assert a == b
    assert {p["name"] for p in project_repo.list_all(conn)} >= {"项目A", "未归类"}


def test_create_and_get(conn):
    _create(conn)
    m = meeting_repo.get_by_uid(conn, "20261121-100000-abcd")
    assert m["title"] == "测试会"
    assert m["status"] == "pending"


def test_list_page_filters(conn):
    _create(conn, uid="u1", project="项目A")
    _create(conn, uid="u2", project="项目B")
    pid_a = project_repo.ensure_project(conn, "项目A")
    items, total = meeting_repo.list_page(conn, project_id=pid_a)
    assert total == 1
    assert items[0]["uid"] == "u1"
    assert items[0]["project_name"] == "项目A"


def test_claim_next_moves_to_transcribing(conn):
    _create(conn, uid="u1")
    _create(conn, uid="u2")
    first = meeting_repo.claim_next(conn, "2026-11-21 10:00:00")
    second = meeting_repo.claim_next(conn, "2026-11-21 10:00:00")
    third = meeting_repo.claim_next(conn, "2026-11-21 10:00:00")
    assert first["uid"] == "u1"
    assert second["uid"] == "u2"
    assert third is None
    assert meeting_repo.get_by_uid(conn, "u1")["status"] == "transcribing"


def test_claim_respects_next_retry_at(conn):
    _create(conn, uid="u1")
    conn.execute("UPDATE meeting SET next_retry_at='2026-11-21 11:00:00'")
    assert meeting_repo.claim_next(conn, "2026-11-21 10:00:00") is None
    assert meeting_repo.claim_next(conn, "2026-11-21 11:00:01")["uid"] == "u1"


def test_set_status_and_reset_for_retry(conn):
    _create(conn, uid="u1")
    m = meeting_repo.get_by_uid(conn, "u1")
    meeting_repo.set_status(conn, m["id"], "failed", "asr_timeout", "超时")
    assert meeting_repo.get_by_uid(conn, "u1")["finished_at"] is not None
    meeting_repo.reset_for_retry(conn, m["id"])
    fresh = meeting_repo.get_by_uid(conn, "u1")
    assert fresh["status"] == "pending"
    assert fresh["finished_at"] is None
    assert fresh["retry_count"] == 1
