"""概览页统计：总量、趋势、状态分布、最近纪要与待办。"""

import json
from datetime import datetime

from app.storage import action_repo


def _month_key(moment: datetime) -> str:
    return moment.strftime("%Y-%m")


def _shift_month(moment: datetime, offset: int) -> datetime:
    year = moment.year
    month = moment.month + offset
    while month <= 0:
        month += 12
        year -= 1
    while month > 12:
        month -= 12
        year += 1
    return datetime(year, month, 1)


def overview(cfg, conn) -> dict:
    now = datetime.now()
    totals = conn.execute(
        "SELECT COUNT(*) AS n, COALESCE(SUM(duration_sec),0) AS dur FROM meeting"
    ).fetchone()
    month_prefix = now.strftime("%Y-%m")
    month_count = conn.execute(
        "SELECT COUNT(*) AS n FROM meeting WHERE substr(recorded_at,1,7)=?",
        (month_prefix,)).fetchone()["n"]
    open_actions = conn.execute(
        "SELECT COUNT(*) AS n FROM action_item WHERE status='open'"
    ).fetchone()["n"]
    projects = conn.execute("SELECT COUNT(*) AS n FROM project").fetchone()["n"]

    status_rows = conn.execute(
        "SELECT status, COUNT(*) AS n FROM meeting GROUP BY status").fetchall()
    status_counts = {row["status"]: row["n"] for row in status_rows}
    done = status_counts.get("done", 0)
    failed = status_counts.get("failed", 0)
    processing = sum(status_counts.get(s, 0) for s in
                     ("uploading", "pending", "transcribing", "minuting",
                      "relating"))

    months = []
    for offset in range(-5, 1):
        moment = _shift_month(now, offset)
        key = _month_key(moment)
        count = conn.execute(
            "SELECT COUNT(*) AS n FROM meeting WHERE substr(recorded_at,1,7)=?",
            (key,)).fetchone()["n"]
        months.append({"key": key, "label": f"{moment.month}月", "count": count})
    peak = max([m["count"] for m in months] + [1])
    for item in months:
        item["height"] = round(item["count"] / peak * 100, 1)

    recent = conn.execute(
        "SELECT m.uid, m.title, m.recorded_at, m.status, m.duration_sec,"
        " m.closed, p.name AS project_name FROM meeting m"
        " JOIN project p ON p.id=m.project_id"
        " ORDER BY m.recorded_at DESC, m.id DESC LIMIT 6").fetchall()
    recent = [dict(row) for row in recent]

    latest_row = conn.execute(
        "SELECT * FROM meeting WHERE status='done' AND minutes IS NOT NULL"
        " ORDER BY id DESC LIMIT 1").fetchone()
    latest = None
    if latest_row:
        latest = dict(latest_row)
        latest["minutes"] = json.loads(latest["minutes"])
        latest["actions"] = action_repo.list_for(conn, latest["id"])[:4]

    recent_actions = conn.execute(
        "SELECT a.task, a.owner, a.due, m.uid, m.title FROM action_item a"
        " JOIN meeting m ON m.id=a.meeting_id"
        " WHERE a.status='open' ORDER BY a.id DESC LIMIT 5").fetchall()

    total = totals["n"] or 0
    return {
        "total": total,
        "month_count": month_count,
        "total_hours": round((totals["dur"] or 0) / 3600, 1),
        "open_actions": open_actions,
        "projects": projects,
        "months": months,
        "status": {"done": done, "processing": processing, "failed": failed},
        "status_pct": {
            "done": round(done / total * 100) if total else 0,
            "processing": round(processing / total * 100) if total else 0,
            "failed": round(failed / total * 100) if total else 0,
        },
        "recent": recent,
        "latest": latest,
        "recent_actions": [dict(row) for row in recent_actions],
        "today": now.strftime("%Y年%m月%d日"),
    }
