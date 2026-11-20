"""只做两类能拿原文举证的关联，不做开放式联想。"""

import json

from app.core import similarity
from app.storage import action_repo, meeting_repo

TASK_MATCH_THRESHOLD = 0.5
TOPIC_MATCH_THRESHOLD = 0.6
MAX_PREVIOUS = 5


def _same_topic(title: str, previous_titles: list[str]) -> bool:
    for previous in previous_titles:
        if not previous or not title:
            continue
        if title == previous or title in previous or previous in title:
            return True
        if similarity.jaccard(title, previous) >= TOPIC_MATCH_THRESHOLD:
            return True
    return False


def build_relations(conn, meeting: dict, minutes: dict) -> list[dict]:
    result: list[dict] = []
    previous_meetings = meeting_repo.previous_done(
        conn, meeting["project_id"], meeting["id"], limit=MAX_PREVIOUS)
    current_actions = minutes.get("actions", [])

    for previous in previous_meetings:
        open_items = action_repo.open_for(conn, previous["id"])
        unmatched = [
            item for item in open_items
            if not any(similarity.jaccard(item["task"], current.get("task", ""))
                       >= TASK_MATCH_THRESHOLD for current in current_actions)
        ]
        if unmatched:
            result.append({
                "target_id": previous["id"],
                "kind": "pending_carryover",
                "detail": f"上次还有 {len(unmatched)} 条待办未见结论",
                "quote": unmatched[0]["task"],
            })

        previous_minutes = json.loads(previous["minutes"]) if previous["minutes"] else {}
        previous_titles = [t.get("title", "")
                           for t in previous_minutes.get("topics", [])]
        for topic in minutes.get("topics", []):
            title = topic.get("title", "")
            if _same_topic(title, previous_titles):
                result.append({
                    "target_id": previous["id"],
                    "kind": "repeat_topic",
                    "detail": f"议题「{title[:18]}」上次也讨论过",
                    "quote": title,
                })
                break
    return result
