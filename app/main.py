import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse

from app.api import auth, projects, upload
from app.api.auth import COOKIE_NAME, verify_token
from app.api.errors import ApiError, api_error_handler
from app.config import Config
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
        if path in {"/login", "/healthz"} or path.startswith("/static/"):
            return await call_next(request)
        token = request.cookies.get(COOKIE_NAME)
        if verify_token(cfg.cookie_secret, token):
            return await call_next(request)
        if path.startswith("/api/"):
            return JSONResponse(
                {"error": {"code": "unauthorized", "message": "未登录"}},
                status_code=401,
            )
        return RedirectResponse("/login", status_code=302)

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    app.include_router(auth.router)
    app.include_router(upload.router)
    app.include_router(projects.router)
    app.include_router(pages.router)
    return app


# 启动方式（单进程）：
# python -m uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000
