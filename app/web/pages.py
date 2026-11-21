from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.core import state
from app.services import dashboard as dashboard_service
from app.services import settings as settings_service
from app.storage import db, files, meeting_repo, project_repo
from app.web import context, render

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    cfg = request.app.state.cfg
    conn = db.connect(cfg.db_path)
    try:
        data = dashboard_service.overview(cfg, conn)
    finally:
        conn.close()
    return HTMLResponse(render.render(
        "dashboard.html", user=request.state.user,
        labels=state.STATUS_LABELS, **data))


@router.get("/meetings", response_class=HTMLResponse)
def meeting_list(request: Request, project_id: int | None = None,
                 status: str | None = None, date: str | None = None,
                 page: int = 1):
    cfg = request.app.state.cfg
    conn = db.connect(cfg.db_path)
    try:
        items, total = meeting_repo.list_page(
            conn, project_id=project_id, status=status, date=date,
            page=max(page, 1), size=15)
        projects = project_repo.list_all(conn)
    finally:
        conn.close()
    groups: list[dict] = []
    for item in items:
        item["progress"] = state.progress_of(item["status"])
        key = (item["recorded_at"] or "")[:7]
        if not groups or groups[-1]["key"] != key:
            try:
                label = f"{int(key[:4])}年{int(key[5:7])}月"
            except (ValueError, TypeError):
                label = "日期未知"
            groups.append({"key": key, "label": label, "items": []})
        groups[-1]["items"].append(item)
    return HTMLResponse(render.render(
        "index.html", groups=groups, projects=projects, total=total,
        page=page, filters={"project_id": project_id, "status": status,
                            "date": date},
        labels=state.STATUS_LABELS, user=request.state.user,
    ))


@router.get("/upload", response_class=HTMLResponse)
def upload_page(request: Request):
    cfg = request.app.state.cfg
    conn = db.connect(cfg.db_path)
    try:
        projects = project_repo.list_all(conn)
        templates = settings_service.list_templates(conn)
        asr = settings_service.asr_settings(cfg, conn)
    finally:
        conn.close()
    try:
        pending = len([p for p in cfg.inbox_dir.iterdir()
                       if p.is_file() and p.suffix.lower() in files.AUDIO_SUFFIXES])
        free_gb = round(files.free_gb(cfg.data_dir), 1)
    except OSError:
        pending, free_gb = 0, 0
    info = {
        "inbox": str(cfg.inbox_dir),
        "free_gb": free_gb,
        "pending": pending,
        "scan_interval": cfg.scan_interval,
        "max_upload_mb": cfg.max_upload_mb,
        "max_duration_min": asr["max_duration_min"],
        "formats": "、".join(sorted(files.AUDIO_SUFFIXES)),
    }
    return HTMLResponse(render.render(
        "upload.html", projects=projects, templates=templates, info=info,
        user=request.state.user))


@router.get("/m/{uid}", response_class=HTMLResponse)
def meeting_page(request: Request, uid: str):
    conn = db.connect(request.app.state.cfg.db_path)
    try:
        meeting = meeting_repo.get_by_uid(conn, uid)
        if not meeting:
            return HTMLResponse("<h1>404</h1><p>会议不存在</p>", status_code=404)
        ctx = context.build_context(conn, meeting)
    finally:
        conn.close()
    return HTMLResponse(render.render(
        "meeting.html", m=meeting, labels=state.STATUS_LABELS,
        progress=state.progress_of(meeting["status"]),
        standalone=False, user=request.state.user, **ctx,
    ))


@router.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request):
    return HTMLResponse(render.render(
        "admin.html", standalone=False, user=request.state.user))
