from pathlib import Path

from fastapi import APIRouter, File, Form, Request, UploadFile

from app.api.errors import ApiError
from app.storage import db, files, meeting_repo, project_repo

router = APIRouter(prefix="/api")
TEMPLATE_KEYS = {"standard", "discussion", "report"}


@router.post("/meetings")
async def upload(
    request: Request,
    file: UploadFile = File(...),
    title: str = Form(""),
    project_name: str = Form(""),
    template_key: str = Form("standard"),
):
    cfg = request.app.state.cfg
    ext = Path(file.filename or "").suffix.lower()
    if ext not in files.AUDIO_SUFFIXES:
        raise ApiError(400, "upload_invalid", "不支持的音频格式")
    project_name = project_name.strip()
    if not project_name:
        raise ApiError(400, "upload_invalid", "必须选择项目")
    if template_key not in TEMPLATE_KEYS:
        raise ApiError(400, "upload_invalid", "未知的纪要模板")
    if files.free_gb(cfg.data_dir) < cfg.min_free_gb:
        raise ApiError(503, "storage_full", "服务器磁盘空间不足")

    safe_title = files.sanitize_title(title or Path(file.filename or "").stem)
    uid = files.new_uid()
    meta = {"project": project_name, "title": safe_title,
            "recorded_at": meeting_repo.now_str()}
    try:
        path, size, _ = files.save_stream(
            file.file, cfg.inbox_dir, uid, safe_title, ext, meta,
            max_bytes=cfg.max_upload_mb * 1024 * 1024,
        )
    except ValueError as exc:
        raise ApiError(413, "too_large", str(exc)) from exc

    conn = db.connect(cfg.db_path)
    try:
        pid = project_repo.ensure_project(conn, project_name)
        meeting_repo.create(
            conn, uid=uid, title=safe_title, project_id=pid,
            recorded_at=meta["recorded_at"], audio_filename=path.name,
            audio_size=size, template_key=template_key, status="uploading",
        )
    except Exception:
        path.unlink(missing_ok=True)
        (cfg.inbox_dir / f"{path.stem}.json").unlink(missing_ok=True)
        raise
    finally:
        conn.close()
    return {"uid": uid}
