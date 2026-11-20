from app.core import state


def test_legal_transitions():
    assert state.can_transition("uploading", "pending")
    assert state.can_transition("pending", "transcribing")
    assert state.can_transition("pending", "failed")
    assert state.can_transition("transcribing", "minuting")
    assert state.can_transition("transcribing", "relating")
    assert state.can_transition("minuting", "done")
    assert state.can_transition("done", "failed")
    assert state.can_transition("failed", "pending")
    assert state.can_transition("done", "pending")


def test_illegal_transitions():
    assert not state.can_transition("pending", "done")
    assert not state.can_transition("uploading", "minuting")
    assert not state.can_transition("done", "transcribing")


def test_resume_stage():
    assert state.resume_stage(None, None) == "transcribe"
    assert state.resume_stage("[]", None) == "minutes"
    assert state.resume_stage("[]", "{}") == "relations"


def test_can_retry():
    assert state.can_retry({"status": "failed", "minutes": None})
    assert state.can_retry({"status": "done", "minutes": None})
    assert not state.can_retry({"status": "done", "minutes": "{}"})
    assert not state.can_retry({"status": "transcribing", "minutes": None})
