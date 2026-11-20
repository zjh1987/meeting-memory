import json

from app.core import state
from app.storage import action_repo, relation_repo

MINUTE_TEMPLATES = {
    "standard": {
        "name": "常规会议",
        "sections": ["summary", "topics", "decisions", "actions", "open_issues"],
    },
    "discussion": {
        "name": "座谈交流",
        "sections": ["summary", "topics", "people", "decisions", "actions"],
    },
    "report": {
        "name": "工作汇报",
        "sections": ["summary", "topics", "open_issues", "actions"],
    },
}


def build_context(conn, meeting: dict) -> dict:
    minutes = json.loads(meeting["minutes"]) if meeting["minutes"] else {}
    transcript = json.loads(meeting["transcript"]) if meeting["transcript"] else []
    project = conn.execute(
        "SELECT name FROM project WHERE id=?", (meeting["project_id"],)
    ).fetchone()
    tmpl = MINUTE_TEMPLATES.get(meeting["template_key"],
                                MINUTE_TEMPLATES["standard"])
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
