import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api import admin, app_update, auth, meetings, projects, templates, upload
from app.api.auth import COOKIE_NAME, read_token
from app.api.errors import ApiError, api_error_handler
from app.config import Config
from app.services import users as user_service
from app.storage import db
from app.web import pages


def create_app(cfg: Config | None = None, start_threads: bool = True) -> FastAPI:
    cfg = cfg or Config.from_env()
    problems = cfg.validate()
    if problems:
        raise RuntimeError("配置错误：" + "；".join(problems))
    cfg.ensure_dirs()
    from app.core.logging import setup_logging
    setup_logging(cfg.log_dir)
    db.init_db(cfg.db_path)
    conn = db.connect(cfg.db_path)
    try:
        user_service.ensure_admin(cfg, conn)
    finally:
        conn.close()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        stop = threading.Event()
        app.state.stop_event = stop
        threads = []
        if start_threads:
            from app.pipeline import harvester, maintainer, worker
            threads = [
                harvester.start(cfg, stop),
                worker.start(cfg, stop),
                maintainer.start(cfg, stop),
            ]
        yield
        stop.set()
        for t in threads:
            t.join(timeout=3)

    app = FastAPI(title="会议记忆", lifespan=lifespan)
    app.state.cfg = cfg
    app.state.limiter = auth.LoginLimiter()
    app.add_exception_handler(ApiError, api_error_handler)

    @app.middleware("http")
    async def auth_guard(request: Request, call_next):
        path = request.url.path
        if path in {"/login", "/reset-help", "/healthz"} \
                or path.startswith("/static/") \
                or path.startswith("/downloads/") \
                or path == "/api/app/android/latest":
            return await call_next(request)
        claims = read_token(cfg.cookie_secret,
                            request.cookies.get(COOKIE_NAME))
        user = None
        if claims:
            conn = db.connect(cfg.db_path)
            try:
                user = user_service.get_user(conn, claims["uid"])
            finally:
                conn.close()
            if user and user["token_version"] != claims["token_version"]:
                user = None
        if user is None:
            if path.startswith("/api/"):
                return JSONResponse(
                    {"error": {"code": "unauthorized", "message": "未登录"}},
                    status_code=401,
                )
            return RedirectResponse("/login", status_code=302)
        request.state.user = user
        if (path == "/admin" or path.startswith("/api/admin")
                or path.startswith("/site")) and user["role"] != "admin":
            if path.startswith("/api/"):
                return JSONResponse(
                    {"error": {"code": "forbidden", "message": "需要管理员权限"}},
                    status_code=403,
                )
            return HTMLResponse(
                "<h1>403</h1><p>该页面仅管理员可访问。</p>", status_code=403)
        return await call_next(request)

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    app.include_router(auth.router)
    app.include_router(app_update.router)
    app.include_router(upload.router)
    app.include_router(projects.router)
    app.include_router(templates.router)
    app.include_router(meetings.router)
    app.include_router(admin.router)
    app.include_router(pages.router)
    # 本地/单机部署时也能直接打开静态归档；Nginx 部署时仍可由 Nginx 直接托管。
    app.mount("/site", StaticFiles(directory=str(cfg.site_dir), html=True),
              name="site")
    return app


# 启动方式（单进程）：
# python -m uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000
