"""跨会议关联：本地确定性规则，不调用大模型、不产生 API 费用。

历史会议按录音时间窗（可配置）回看，并可用“关联提示词”里的同义词组
做关键词补充匹配；只读取历史议题与未闭环待办这两类结构化数据。
"""

import json
import re
from datetime import datetime, timedelta

from app.core import similarity
from app.storage import action_repo, meeting_repo

TASK_MATCH_THRESHOLD = 0.5
TOPIC_MATCH_THRESHOLD = 0.6
MAX_PREVIOUS = 10
WINDOW_DAYS = 180
MAX_RESULTS = 12
SCAN_LIMIT = 60

_SPLIT = re.compile(r"[,，、;；/|]+")


def parse_hint_groups(hint: str) -> list[list[str]]:
    """把关联提示词解析成同义词组；每行一组，用逗号/顿号分隔。"""
    groups: list[list[str]] = []
    for line in (hint or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        terms = [term.strip() for term in _SPLIT.split(line)]
        terms = [term for term in terms if 2 <= len(term) <= 32]
        if terms:
            groups.append(terms)
    return groups


def _shared_term(left: str, right: str, groups: list[list[str]]) -> str:
    """返回左右文本命中的同一同义词组里的词；没有命中返回空串。"""
    if not groups:
        return ""
    for group in groups:
        if not any(term in left for term in group):
            continue
        if not any(term in right for term in group):
            continue
        for term in group:
            if term in left:
                return term
    return ""


def _same_topic(title: str, previous_titles: list[str],
                groups: list[list[str]], threshold: float) -> bool:
    for previous in previous_titles:
        if not previous or not title:
            continue
        if title == previous or title in previous or previous in title:
            return True
        if similarity.jaccard(title, previous) >= threshold:
            return True
        if _shared_term(title, previous, groups):
            return True
    return False


def _topic_text(topic: dict) -> str:
    points = " ".join(str(point) for point in topic.get("points") or [])
    return f"{topic.get('title') or ''} {points}".strip()


def _meeting_text(minutes: dict, open_items: list[dict]) -> str:
    parts = [_topic_text(topic) for topic in minutes.get("topics", [])]
    parts.extend(str(item.get("task") or "") for item in open_items)
    return "\n".join(parts)


def _since(meeting: dict, window_days: int) -> str | None:
    if window_days <= 0:
        return None
    try:
        base = datetime.strptime(meeting["recorded_at"], "%Y-%m-%d %H:%M:%S")
    except (KeyError, TypeError, ValueError):
        base = datetime.now()
    return (base - timedelta(days=window_days)).strftime("%Y-%m-%d %H:%M:%S")


def _load_previous(conn, previous: dict) -> tuple[dict, list[dict]]:
    open_items = action_repo.open_for(conn, previous["id"])
    try:
        minutes = json.loads(previous["minutes"]) if previous["minutes"] else {}
    except (TypeError, ValueError):
        minutes = {}
    return minutes, open_items


def build_relations(conn, meeting: dict, minutes: dict,
                    options: dict | None = None) -> list[dict]:
    options = options or {}
    if options.get("enabled") is False:
        return []
    try:
        max_previous = max(1, min(int(options.get("max_previous", MAX_PREVIOUS)), 50))
        window_days = max(0, int(options.get("window_days", WINDOW_DAYS)))
        topic_threshold = float(options.get("topic_threshold", TOPIC_MATCH_THRESHOLD))
        task_threshold = float(options.get("task_threshold", TASK_MATCH_THRESHOLD))
    except (TypeError, ValueError):
        max_previous, window_days = MAX_PREVIOUS, WINDOW_DAYS
        topic_threshold, task_threshold = TOPIC_MATCH_THRESHOLD, TASK_MATCH_THRESHOLD
    groups = parse_hint_groups(options.get("hint", ""))

    candidates = meeting_repo.relation_candidates(
        conn, meeting["project_id"], meeting["id"],
        since=_since(meeting, window_days), limit=SCAN_LIMIT)

    current_topics = minutes.get("topics", [])
    current_actions = minutes.get("actions", [])
    current_text = "\n".join(
        [_topic_text(topic) for topic in current_topics]
        + [str(action.get("task") or "") for action in current_actions])

    # 最近 N 场始终参与；更早的会议只有命中关联关键词时才纳入。
    selected: list[tuple[dict, dict, list[dict]]] = []
    for index, previous in enumerate(candidates):
        if index >= max_previous and not groups:
            break
        previous_minutes, open_items = _load_previous(conn, previous)
        keyword_hit = bool(groups) and bool(_shared_term(
            current_text, _meeting_text(previous_minutes, open_items), groups))
        if index < max_previous or keyword_hit:
            selected.append((previous, previous_minutes, open_items))
        if len(selected) >= max_previous * 2:
            break

    result: list[dict] = []
    matched_topics: set[str] = set()
    for previous, previous_minutes, open_items in selected:
        if len(result) >= MAX_RESULTS:
            break
        unmatched = []
        for item in open_items:
            task = str(item.get("task") or "")
            matched = any(
                similarity.jaccard(task, str(current.get("task") or "")) >= task_threshold
                or _shared_term(task, str(current.get("task") or ""), groups)
                for current in current_actions)
            if not matched:
                unmatched.append(item)
        if unmatched:
            result.append({
                "target_id": previous["id"],
                "kind": "pending_carryover",
                "detail": f"上次还有 {len(unmatched)} 条待办未见结论",
                "quote": unmatched[0]["task"],
            })

        previous_topics = previous_minutes.get("topics", [])
        previous_titles = [str(topic.get("title") or "") for topic in previous_topics]
        previous_topic_text = "\n".join(_topic_text(topic) for topic in previous_topics)
        for topic in current_topics:
            title = str(topic.get("title") or "")
            if not title or title in matched_topics:
                continue
            if not _same_topic(title, previous_titles, groups, topic_threshold):
                continue
            matched_topics.add(title)
            detail = f"议题「{title[:18]}」上次也讨论过"
            keyword = _shared_term(_topic_text(topic), previous_topic_text, groups)
            if keyword and not any(
                    similarity.jaccard(title, previous) >= topic_threshold
                    or title in previous or previous in title
                    for previous in previous_titles if previous):
                detail += f"（关键词：{keyword}）"
            result.append({
                "target_id": previous["id"],
                "kind": "repeat_topic",
                "detail": detail,
                "quote": title,
            })
            break
    return result
