"""页面渲染与静态归档。

纪要字段是统一的，会议类型模板只决定"展示哪几块、怎么称呼"，
这样跨会议关联才有稳定的字段可比对。
"""

import json
from datetime import datetime

from jinja2 import Environment, FileSystemLoader, select_autoescape

import config
import store

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

STATUS_LABEL = {
    "pending": "排队中",
    "transcribing": "转写中",
    "minuting": "生成纪要中",
    "done": "已完成",
    "failed": "处理失败",
}

env = Environment(
    loader=FileSystemLoader(str(config.TEMPLATE_DIR)),
    autoescape=select_autoescape(["html"]),
)


def _mmss(seconds) -> str:
    try:
        total = int(float(seconds))
    except (TypeError, ValueError):
        return "00:00"
    return f"{total // 60:02d}:{total % 60:02d}"


env.filters["mmss"] = _mmss


def build_context(uid: str) -> dict | None:
    m = store.get_meeting(uid)
    if not m:
        return None

    minutes = json.loads(m["minutes"]) if m["minutes"] else {}
    transcript = json.loads(m["transcript"]) if m["transcript"] else []
    tmpl = MINUTE_TEMPLATES.get(m["template_key"], MINUTE_TEMPLATES["standard"])

    return {
        "m": m,
        "minutes": minutes,
        "transcript": transcript,
        "tmpl": tmpl,
        "actions": store.get_actions(m["id"]),
        "relations": store.get_relations(m["id"]),
        "status_label": STATUS_LABEL.get(m["status"], m["status"]),
        "finished": m["status"] == "done",
    }


def render_meeting(uid: str) -> str | None:
    ctx = build_context(uid)
    if not ctx:
        return None
    return env.get_template("meeting.html").render(**ctx)


def render_index() -> str:
    meetings = store.list_meetings()
    for m in meetings:
        m["status_label"] = STATUS_LABEL.get(m["status"], m["status"])
    return env.get_template("index.html").render(meetings=meetings)


def export_static(uid: str) -> None:
    """把完成的纪要落到固定路径，便于归档或挂到 Nginx。"""
    html = render_meeting(uid)
    if not html:
        return
    m = store.get_meeting(uid)
    day = (m["recorded_at"] or "")[:10].replace("-", "/")
    target = config.SITE_DIR / day / uid / "index.html"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(html, encoding="utf-8")
