from fastapi import APIRouter, Request

from app.storage import db, project_repo

router = APIRouter(prefix="/api")


@router.get("/projects")
def list_projects(request: Request):
    conn = db.connect(request.app.state.cfg.db_path)
    try:
        return {"items": project_repo.list_all(conn)}
    finally:
        conn.close()
