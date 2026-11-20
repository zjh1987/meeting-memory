from fastapi import APIRouter, Request

from app.api.errors import ApiError
from app.core import state
from app.storage import db, meeting_repo

router = APIRouter(prefix="/api")


@router.get("/meetings")
def list_meetings(request: Request, project_id: int | None = None,
                  status: str | None = None, date: str | None = None,
                  page: int = 1, size: int = 20):
    conn = db.connect(request.app.state.cfg.db_path)
    try:
        items, total = meeting_repo.list_page(
            conn, project_id=project_id, status=status,
            date=date, page=max(page, 1), size=min(max(size, 1), 100))
        return {"items": items, "total": total}
    finally:
        conn.close()


@router.get("/meetings/{uid}/status")
def meeting_status(request: Request, uid: str):
    conn = db.connect(request.app.state.cfg.db_path)
    try:
        m = meeting_repo.get_by_uid(conn, uid)
        if not m:
            raise ApiError(404, "not_found", "会议不存在")
        return {
            "status": m["status"],
            "status_label": state.STATUS_LABELS.get(m["status"], m["status"]),
            "error_code": m["error_code"],
            "error_msg": m["error_msg"],
            "retry_count": m["retry_count"],
            "can_retry": state.can_retry(m),
        }
    finally:
        conn.close()
