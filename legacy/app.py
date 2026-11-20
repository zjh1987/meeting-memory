"""最小原型的入口。

启动：python app.py
访问：http://127.0.0.1:8000    默认口令 demo1234

注意：这是单进程原型，worker 跑在后台线程里，不要用 --workers > 1 启动。
"""

import hashlib
import re
import threading
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

import config
import pipeline
import render
import store

AUTH_TOKEN = hashlib.sha256(f"v1::{config.APP_PASSWORD}".encode()).hexdigest()[:32]
PUBLIC_PATHS = {"/login", "/healthz"}


@asynccontextmanager
async def lifespan(_app: FastAPI):
    store.init_db()
    pipeline.start()
    print(f"[启动] 数据目录 {config.DATA_DIR}")
    print(f"[启动] 访问口令 {config.APP_PASSWORD}   地址 http://127.0.0.1:8000")
    yield


app = FastAPI(lifespan=lifespan, title="会议记忆原型")


@app.middleware("http")
async def auth_guard(request: Request, call_next):
    path = request.url.path
    if path in PUBLIC_PATHS:
        return await call_next(request)
    if request.cookies.get("auth") == AUTH_TOKEN:
        return await call_next(request)
    if path.startswith("/api/"):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return RedirectResponse("/login", status_code=302)


# ---------------------------------------------------------------- 页面

@app.get("/login", response_class=HTMLResponse)
def login_page():
    return render.env.get_template("login.html").render(error=None)


@app.post("/login")
def login_submit(password: str = Form("")):
    if password != config.APP_PASSWORD:
        return HTMLResponse(
            render.env.get_template("login.html").render(error="口令不正确"),
            status_code=401,
        )
    resp = RedirectResponse("/", status_code=302)
    resp.set_cookie("auth", AUTH_TOKEN, httponly=True, samesite="lax", max_age=86400 * 7)
    return resp


@app.get("/", response_class=HTMLResponse)
def index():
    return render.render_index()


@app.get("/m/{uid}", response_class=HTMLResponse)
def meeting_page(uid: str):
    html = render.render_meeting(uid)
    if html is None:
        return HTMLResponse("<h1>404</h1><p>会议不存在</p>", status_code=404)
    return HTMLResponse(html)


@app.get("/healthz")
def healthz():
    return {"ok": True}


# ---------------------------------------------------------------- 接口

@app.get("/api/status/{uid}")
def api_status(uid: str):
    m = store.get_meeting(uid)
    if not m:
        return JSONResponse({"error": "not found"}, status_code=404)
    return {
        "status": m["status"],
        "status_label": render.STATUS_LABEL.get(m["status"], m["status"]),
        "error": m["error"],
    }


def _new_uid() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]


def _safe(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*\r\n]', "-", name).strip() or "未命名会议"


@app.post("/api/upload")
async def upload(
    file: UploadFile = File(...),
    title: str = Form("未命名会议"),
    project: str = Form(config.DEFAULT_PROJECT),
):
    """真实设备/手机的接入点：先写 .part，写完再改名。"""
    uid = _new_uid()
    title = _safe(title)
    suffix = Path(file.filename or "a.m4a").suffix.lower() or ".m4a"
    stem = f"{uid}__{title}"

    part = config.INBOX_DIR / f"{stem}{suffix}.part"
    with part.open("wb") as f:
        while True:
            chunk = await file.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)

    (config.INBOX_DIR / f"{stem}.json").write_text(
        '{"project": "%s"}' % project, encoding="utf-8"
    )
    part.rename(config.INBOX_DIR / f"{stem}{suffix}")
    return {"uid": uid, "status": "uploaded"}


@app.post("/api/dev/simulate")
def simulate():
    """演示用：模拟设备把文件写一半、再改名，验证服务端不会转写半截音频。"""
    uid = _new_uid()
    title = "三季度进度会"
    stem = f"{uid}__{title}"

    part = config.INBOX_DIR / f"{stem}.m4a.part"
    part.write_bytes(b"\x00" * 200_000)

    def finish():
        part.rename(config.INBOX_DIR / f"{stem}.m4a")

    threading.Timer(2.0, finish).start()
    return {"uid": uid, "status": "uploading"}


if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=False)
