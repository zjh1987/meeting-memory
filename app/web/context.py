import json

from app.core import state
from app.services import settings as settings_service
from app.storage import action_repo, relation_repo


def build_context(conn, meeting: dict) -> dict:
    minutes = json.loads(meeting["minutes"]) if meeting["minutes"] else {}
    transcript = json.loads(meeting["transcript"]) if meeting["transcript"] else []
    project = conn.execute(
        "SELECT name FROM project WHERE id=?", (meeting["project_id"],)
    ).fetchone()
    tmpl = settings_service.get_template(conn, meeting["template_key"])
    return {
        "minutes": minutes,
        "transcript": transcript,
        "actions": action_repo.list_for(conn, meeting["id"]),
        "relations": relation_repo.list_for(conn, meeting["id"]),
        "tmpl": tmpl,
        "project_name": project["name"] if project else "未归类",
        "finished": meeting["status"] == "done",
        "can_retry": state.can_retry(meeting),
    }
