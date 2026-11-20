"""扫描 inbox，只接收完整文件；.part 一律跳过。"""

import json
import threading
import traceback
from datetime import datetime
from pathlib import Path

from app.config import Config
from app.storage import db, files, meeting_repo, project_repo


def _read_meta(path: Path, fallback_title: str) -> dict:
    meta_path = path.with_suffix(".json")
    data: dict = {}
    if meta_path.exists():
        try:
            data = json.loads(meta_path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            data = {}
        meta_path.unlink(missing_ok=True)
    mtime = datetime.fromtimestamp(path.stat().st_mtime)
    return {
        "project": (data.get("project") or "未归类").strip() or "未归类",
        "title": (data.get("title") or fallback_title).strip() or fallback_title,
        "recorded_at": data.get("recorded_at")
        or mtime.strftime("%Y-%m-%d %H:%M:%S"),
    }


def harvest_once(cfg: Config) -> int:
    conn = db.connect(cfg.db_path)
    moved = 0
    try:
        for path in sorted(cfg.inbox_dir.iterdir()):
            if not path.is_file():
                continue
            if path.suffix.lower() not in files.AUDIO_SUFFIXES:
                continue  # .part 与旁挂 JSON 都在这里被忽略
            uid, title = files.split_stem(path.stem)
            meta = _read_meta(path, title)
            dest = files.move_to_ready(path, cfg.ready_dir)
            row = meeting_repo.get_by_uid(conn, uid)
            if row is None:
                pid = project_repo.ensure_project(conn, meta["project"])
                meeting_repo.create(
                    conn, uid=uid, title=meta["title"], project_id=pid,
                    recorded_at=meta["recorded_at"], audio_filename=dest.name,
                    audio_size=dest.stat().st_size, status="pending",
                )
            else:
                fields = {"audio_filename": dest.name,
                          "audio_size": dest.stat().st_size}
                if row["status"] == "uploading":
                    fields["status"] = "pending"
                meeting_repo.update_fields(conn, row["id"], **fields)
            moved += 1
    finally:
        conn.close()
    return moved


def start(cfg: Config, stop: threading.Event) -> threading.Thread:
    def loop() -> None:
        while not stop.is_set():
            try:
                harvest_once(cfg)
            except Exception:
                traceback.print_exc()
            stop.wait(cfg.scan_interval)

    thread = threading.Thread(target=loop, daemon=True, name="harvester")
    thread.start()
    return thread
