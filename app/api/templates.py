"""移动端可用的纪要模板列表（只读）。"""

from fastapi import APIRouter, Request

from app.services import settings as settings_service
from app.storage import db

router = APIRouter(prefix="/api")


@router.get("/templates")
def list_templates(request: Request):
    conn = db.connect(request.app.state.cfg.db_path)
    try:
        items = settings_service.list_templates(conn)
    finally:
        conn.close()
    return {
        "items": [
            {
                "key": item["key"],
                "name": item["name"],
                "description": item["description"],
                "scene": item["scene"],
                "sections": item["sections"],
            }
            for item in items
        ]
    }
