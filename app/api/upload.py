import re
import sqlite3
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, File, Form, Request, UploadFile

from app.api.errors import ApiError
from app.services import settings as settings_service
from app.storage import db, files, meeting_repo, project_repo

router = APIRouter(prefix="/api")

# Android 在用户未填标题时自动生成的时间名，视为“未编辑”，可由纪要自动命名。
AUTO_TITLE = re.compile(r"^\d{1,2}月\d{1,2}日\s+\d{1,2}:\d{2}\s*录音$")


@router.post("/meetings")
def upload(
    request: Request,
    file: UploadFile = File(...),
    title: str = Form(""),
    project_name: str = Form(""),
    template_key: str = Form(""),
    recorded_at: str = Form(""),
):
    cfg = request.app.state.cfg
    ext = Path(file.filename or "").suffix.lower()
    if ext not in files.AUDIO_SUFFIXES:
        raise ApiError(400, "upload_invalid", "不支持的音频格式")
    project_name = project_name.strip()
    if not project_name:
        raise ApiError(400, "upload_invalid", "必须选择项目")
    recorded_raw = recorded_at.strip()
    if recorded_raw:
        try:
            recorded_value = datetime.strptime(
                recorded_raw, "%Y-%m-%d %H:%M:%S"
            ).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError as exc:
            raise ApiError(400, "upload_invalid", "录音时间格式不正确") from exc
    else:
        recorded_value = meeting_repo.now_str()
    conn = db.connect(cfg.db_path)
    try:
        template_keys = {t["key"] for t in settings_service.list_templates(conn)}
        if not template_key:
            template_key = settings_service.default_template_key(conn)
        elif template_key not in template_keys:
            raise ApiError(400, "upload_invalid", "未知的纪要模板")
    finally:
        conn.close()
    if files.free_gb(cfg.data_dir) < cfg.min_free_gb:
        raise ApiError(503, "storage_full", "服务器磁盘空间不足")

    raw_title = title.strip()
    title_auto = 1 if not raw_title or AUTO_TITLE.fullmatch(raw_title) else 0
    safe_title = files.sanitize_title(raw_title or Path(file.filename or "").stem)
    uid = files.new_uid()
    meta = {"project": project_name, "title": safe_title,
            "recorded_at": recorded_value}
    try:
        path, size, _ = files.save_stream(
            file.file, cfg.inbox_dir, uid, safe_title, ext, meta,
            max_bytes=cfg.max_upload_mb * 1024 * 1024,
        )
    except ValueError as exc:
        raise ApiError(413, "too_large", str(exc)) from exc

    meta_path = cfg.inbox_dir / f"{path.stem}.json"
    if size == 0:
        path.unlink(missing_ok=True)
        meta_path.unlink(missing_ok=True)
        raise ApiError(400, "upload_invalid", "文件为空")

    conn = db.connect(cfg.db_path)
    try:
        pid = project_repo.ensure_project(conn, project_name)
        meeting_repo.create(
            conn, uid=uid, title=safe_title, project_id=pid,
            recorded_at=meta["recorded_at"], audio_filename=path.name,
            audio_size=size, template_key=template_key, status="uploading",
            owner_id=request.state.user["id"], title_auto=title_auto,
        )
    except sqlite3.IntegrityError:
        # Harvester 可能已抢先接管该文件并建了同名 uid 的行。
        if meeting_repo.get_by_uid(conn, uid) is not None:
            return {"uid": uid}
        path.unlink(missing_ok=True)
        meta_path.unlink(missing_ok=True)
        raise
    except Exception:
        if meeting_repo.get_by_uid(conn, uid) is None:
            path.unlink(missing_ok=True)
            meta_path.unlink(missing_ok=True)
        raise
    finally:
        conn.close()
    return {"uid": uid}
