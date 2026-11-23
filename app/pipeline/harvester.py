"""扫描 inbox，只接收完整文件；.part 一律跳过。"""

import json
import re
import shutil
import threading
import traceback
from datetime import datetime
from pathlib import Path

from app.config import Config
from app.core.logging import log_event
from app.services import settings as settings_service
from app.storage import db, files, meeting_repo, project_repo

UID_PATTERN = re.compile(r"^[A-Za-z0-9-]{1,64}$")
TIME_FMT = "%Y-%m-%d %H:%M:%S"


def _safe_uid(raw: str) -> str | None:
    """只接受时间戳式的 uid，避免文件名把路径带到 inbox 之外。"""
    return raw if UID_PATTERN.fullmatch(raw or "") else None


def _safe_recorded_at(raw, path: Path) -> str:
    """非法时间回退文件 mtime，保证归档路径可控。"""
    if raw:
        try:
            return datetime.strptime(str(raw), TIME_FMT).strftime(TIME_FMT)
        except ValueError:
            log_event("warn", "invalid_recorded_at", value=str(raw)[:100],
                      filename=path.name)
    mtime = datetime.fromtimestamp(path.stat().st_mtime)
    return mtime.strftime(TIME_FMT)


def _read_meta(path: Path, fallback_title: str) -> dict:
    meta_path = path.with_suffix(".json")
    data: dict = {}
    if meta_path.exists():
        try:
            loaded = json.loads(meta_path.read_text(encoding="utf-8"))
            data = loaded if isinstance(loaded, dict) else {}
        except (ValueError, OSError):
            data = {}
    return {
        "project": (data.get("project") or "未归类").strip() or "未归类",
        "title": (data.get("title") or fallback_title).strip() or fallback_title,
        "recorded_at": _safe_recorded_at(data.get("recorded_at"), path),
        "template_key": str(data.get("template_key") or "").strip(),
        "meta_path": meta_path,
    }


def _harvest_one(cfg: Config, conn, path: Path) -> bool:
    uid, title = files.split_stem(path.stem)
    safe_uid = _safe_uid(uid)
    if safe_uid is None:
        # 设备直接投放的文件名可能含中文/空格，自动生成 uid，保留原名作为标题。
        safe_uid = files.new_uid()
        title = title or path.stem
        log_event("info", "generated_uid", uid=safe_uid, filename=path.name)

    meta = _read_meta(path, title)
    template_key = meta["template_key"]
    valid_templates = {item["key"] for item in
                       settings_service.list_templates(conn)}
    if not template_key or template_key not in valid_templates:
        template_key = settings_service.default_template_key(conn)
    row = meeting_repo.get_by_uid(conn, safe_uid)
    if row is None:
        pid = project_repo.ensure_project(conn, meta["project"])
        meeting_id = meeting_repo.create(
            conn, uid=safe_uid, title=meta["title"], project_id=pid,
            recorded_at=meta["recorded_at"], audio_filename=path.name,
            template_key=template_key, status="uploading",
        )
    else:
        meeting_id = row["id"]

    try:
        dest = files.move_to_ready(path, cfg.ready_dir)
    except Exception:
        traceback.print_exc()
        log_event("warn", "harvest_move_failed", uid=safe_uid,
                  filename=path.name)
        return False

    try:
        meeting_repo.update_fields(
            conn, meeting_id, audio_filename=dest.name,
            audio_size=dest.stat().st_size, status="pending")
    except Exception as exc:
        traceback.print_exc()
        log_event("warn", "harvest_update_failed", uid=safe_uid,
                  filename=path.name, detail=str(exc)[:500])
        try:
            shutil.move(str(dest), str(cfg.inbox_dir / dest.name))
        except OSError:
            traceback.print_exc()
        return False

    meta["meta_path"].unlink(missing_ok=True)
    return True


def harvest_once(cfg: Config) -> int:
    conn = db.connect(cfg.db_path)
    moved = 0
    try:
        for path in sorted(cfg.inbox_dir.iterdir()):
            if not path.is_file():
                continue
            if path.suffix.lower() not in files.AUDIO_SUFFIXES:
                continue  # .part 与旁挂 JSON 都在这里被忽略
            try:
                if _harvest_one(cfg, conn, path):
                    moved += 1
            except Exception:
                traceback.print_exc()
                log_event("warn", "harvest_failed", filename=path.name)
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
