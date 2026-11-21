"""静态归档：每场会议一个独立 HTML，另有日索引与总索引。"""

import os
from datetime import datetime
from pathlib import Path

from app.config import Config
from app.storage import db
from app.web import render

DATE_FMT = "%Y-%m-%d"


def _safe_day(recorded_at: str) -> str:
    """非法日期回退当天，避免 recorded_at 把归档写到 site 之外。"""
    try:
        return datetime.strptime((recorded_at or "")[:10], DATE_FMT).strftime(
            DATE_FMT)
    except ValueError:
        return datetime.now().strftime(DATE_FMT)


def _checked(cfg: Config, target: Path) -> Path:
    site = cfg.site_dir.resolve()
    resolved = target.resolve()
    if resolved != site and site not in resolved.parents:
        raise ValueError(f"归档路径越界：{target}")
    return target


def _atomic_write(target: Path, text: str) -> None:
    part = target.with_name(target.name + ".part")
    part.write_text(text, encoding="utf-8")
    os.replace(str(part), str(target))


def day_dir(cfg: Config, recorded_at: str) -> Path:
    return cfg.site_dir.joinpath(*_safe_day(recorded_at).split("-"))


def write_meeting(cfg: Config, meeting: dict, html: str) -> Path:
    target = day_dir(cfg, meeting["recorded_at"]) / meeting["uid"] / "index.html"
    _checked(cfg, target)
    target.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(target, html)
    return target


def rebuild_all(cfg: Config) -> int:
    """用当前模板重写全部已完成会议的静态归档，并刷新索引。"""
    from app.core import state
    from app.web import context
    conn = db.connect(cfg.db_path)
    count = 0
    try:
        rows = conn.execute(
            "SELECT * FROM meeting WHERE status='done' ORDER BY recorded_at"
        ).fetchall()
        for row in rows:
            meeting = dict(row)
            ctx = context.build_context(conn, meeting)
            html = render.render("meeting.html", m=meeting, standalone=True,
                                 labels=state.STATUS_LABELS,
                                 progress=state.progress_of(meeting["status"]),
                                 **ctx)
            write_meeting(cfg, meeting, html)
            count += 1
    finally:
        conn.close()
    refresh_indices(cfg)
    return count


def refresh_indices(cfg: Config) -> None:
    conn = db.connect(cfg.db_path)
    try:
        rows = conn.execute(
            "SELECT m.uid, m.title, m.recorded_at, p.name AS project_name"
            " FROM meeting m JOIN project p ON p.id=m.project_id"
            " WHERE m.status='done' ORDER BY m.recorded_at"
        ).fetchall()
    finally:
        conn.close()

    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(_safe_day(row["recorded_at"]), []).append(dict(row))

    days = []
    for day in sorted(groups, reverse=True):
        items = sorted(groups[day], key=lambda x: x["recorded_at"], reverse=True)
        html = render.render("day_index.html", day=day, meetings=items,
                             standalone=True)
        target = day_dir(cfg, day) / "index.html"
        _checked(cfg, target)
        target.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(target, html)
        days.append({"day": day, "count": len(items)})

    root = render.render("root_index.html", days=days, standalone=True)
    cfg.site_dir.mkdir(parents=True, exist_ok=True)
    target = cfg.site_dir / "index.html"
    _checked(cfg, target)
    _atomic_write(target, root)
