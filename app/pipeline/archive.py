"""静态归档：每场会议一个独立 HTML，另有日索引与总索引。"""

from pathlib import Path

from app.config import Config
from app.storage import db
from app.web import render


def day_dir(cfg: Config, recorded_at: str) -> Path:
    return cfg.site_dir.joinpath(*recorded_at[:10].split("-"))


def write_meeting(cfg: Config, meeting: dict, html: str) -> Path:
    target = day_dir(cfg, meeting["recorded_at"]) / meeting["uid"] / "index.html"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(html, encoding="utf-8")
    return target


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
        groups.setdefault(row["recorded_at"][:10], []).append(dict(row))

    days = []
    for day in sorted(groups, reverse=True):
        items = sorted(groups[day], key=lambda x: x["recorded_at"], reverse=True)
        html = render.render("day_index.html", day=day, meetings=items,
                             standalone=True)
        target = cfg.site_dir.joinpath(*day.split("-")) / "index.html"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(html, encoding="utf-8")
        days.append({"day": day, "count": len(items)})

    root = render.render("root_index.html", days=days, standalone=True)
    cfg.site_dir.mkdir(parents=True, exist_ok=True)
    (cfg.site_dir / "index.html").write_text(root, encoding="utf-8")
