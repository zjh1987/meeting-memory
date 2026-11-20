from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.core import state
from app.storage import db, meeting_repo, project_repo
from app.web import render

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
    finally:
        conn.close()
    return HTMLResponse(render.render(
        "index.html", meetings=items, projects=projects, total=total,
        page=page, filters={"project_id": project_id, "status": status, "date": date},
        labels=state.STATUS_LABELS,
    ))
