from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.core import state
from app.services import settings as settings_service
from app.storage import db, meeting_repo, project_repo
from app.web import context, render

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def home(request: Request, project_id: int | None = None,
         status: str | None = None, date: str | None = None, page: int = 1):
    conn = db.connect(request.app.state.cfg.db_path)
    try:
        items, total = meeting_repo.list_page(
            conn, project_id=project_id, status=status,
            date=date, page=max(page, 1))
        projects = project_repo.list_all(conn)
        templates = settings_service.list_templates(conn)
    finally:
        conn.close()
    for item in items:
        item["progress"] = state.progress_of(item["status"])
    return HTMLResponse(render.render(
        "index.html", meetings=items, projects=projects, templates=templates,
        total=total,
        page=page, filters={"project_id": project_id, "status": status, "date": date},
        labels=state.STATUS_LABELS,
    ))


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
        standalone=False, **ctx,
    ))


@router.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request):
    return HTMLResponse(render.render("admin.html", standalone=False))
