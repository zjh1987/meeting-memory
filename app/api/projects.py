from fastapi import APIRouter, Request

from app.storage import db, project_repo

router = APIRouter(prefix="/api")


@router.get("/projects")
def list_projects(request: Request):
    user = request.state.user
    owner_id = None if user["role"] == "admin" else user["id"]
    conn = db.connect(request.app.state.cfg.db_path)
    try:
        return {"items": project_repo.list_all(conn, owner_id=owner_id)}
    finally:
        conn.close()
