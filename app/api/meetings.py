from fastapi import APIRouter, Body, Request

from app.api.auth import can_access_meeting, require_admin
from app.api.errors import ApiError
from app.core import state
from app.storage import db, meeting_repo

router = APIRouter(prefix="/api")


@router.get("/meetings")
def list_meetings(request: Request, project_id: int | None = None,
                  status: str | None = None, date: str | None = None,
                  page: int = 1, size: int = 20):
    user = request.state.user
    owner_id = None if user["role"] == "admin" else user["id"]
    conn = db.connect(request.app.state.cfg.db_path)
    try:
        items, total = meeting_repo.list_page(
            conn, project_id=project_id, status=status, owner_id=owner_id,
            date=date, page=max(page, 1), size=min(max(size, 1), 100))
        return {"items": items, "total": total}
    finally:
        conn.close()


@router.get("/meetings/{uid}/status")
def meeting_status(request: Request, uid: str):
    conn = db.connect(request.app.state.cfg.db_path)
    try:
        m = meeting_repo.get_by_uid(conn, uid)
        if not can_access_meeting(request.state.user, m):
            raise ApiError(404, "not_found", "会议不存在")
        return {
            "status": m["status"],
            "status_label": state.STATUS_LABELS.get(m["status"], m["status"]),
            "progress": state.progress_of(m["status"]),
            "closed": bool(m["closed"]),
            "error_code": m["error_code"],
            "error_msg": m["error_msg"],
            "retry_count": m["retry_count"],
            "can_retry": state.can_retry(m),
        }
    finally:
        conn.close()


@router.post("/meetings/{uid}/title")
def rename_meeting(request: Request, uid: str, payload: dict = Body(...)):
    conn = db.connect(request.app.state.cfg.db_path)
    try:
        m = meeting_repo.get_by_uid(conn, uid)
        if not can_access_meeting(request.state.user, m):
            raise ApiError(404, "not_found", "会议不存在")
        title = " ".join(str(payload.get("title") or "").split())
        if not title:
            raise ApiError(400, "invalid_title", "会议名称不能为空")
        if len(title) > 60:
            raise ApiError(400, "invalid_title", "会议名称不能超过 60 个字符")
        meeting_repo.update_fields(conn, m["id"], title=title, title_auto=0)
        return {"ok": True, "title": title}
    finally:
        conn.close()


@router.post("/meetings/{uid}/retry")
def retry_meeting(request: Request, uid: str):
    require_admin(request)
    conn = db.connect(request.app.state.cfg.db_path)
    try:
        m = meeting_repo.get_by_uid(conn, uid)
        if not m:
            raise ApiError(404, "not_found", "会议不存在")
        if not state.can_retry(m):
            raise ApiError(409, "invalid_state", "当前状态不允许重试")
        meeting_repo.reset_for_retry(conn, m["id"])
        return {"status": "pending"}
    finally:
        conn.close()
