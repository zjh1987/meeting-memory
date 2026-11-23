import hashlib
import hmac
import time
from collections import defaultdict, deque

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.services import users as user_service
from app.storage import db

router = APIRouter()
COOKIE_NAME = "mm_session"
SESSION_SECONDS = 7 * 86400


def make_token(secret: str, expires_ts: int, user_id: int = 0,
               token_version: int = 0) -> str:
    payload = f"{expires_ts}.{user_id}.{token_version}"
    sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def read_token(secret: str, token: str | None,
               now_ts: int | None = None) -> dict | None:
    if not token:
        return None
    try:
        payload, sig = token.rsplit(".", 1)
        expires_raw, user_raw, version_raw = payload.split(".")
        expires = int(expires_raw)
        user_id = int(user_raw)
        token_version = int(version_raw)
    except (ValueError, AttributeError):
        return None
    expected = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return None
    if expires <= (int(time.time()) if now_ts is None else now_ts):
        return None
    return {"uid": user_id, "token_version": token_version,
            "expires": expires}


def verify_token(secret: str, token: str | None,
                 now_ts: int | None = None) -> bool:
    return read_token(secret, token, now_ts) is not None


class LoginLimiter:
    def __init__(self, max_attempts: int = 5, window_sec: int = 60):
        self.max_attempts = max_attempts
        self.window_sec = window_sec
        self._hits: dict[str, deque] = defaultdict(deque)

    def allow(self, ip: str, now: float | None = None) -> bool:
        moment = time.time() if now is None else now
        hits = self._hits[ip]
        while hits and hits[0] <= moment - self.window_sec:
            hits.popleft()
        if len(hits) >= self.max_attempts:
            return False
        hits.append(moment)
        return True


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    from app.web import render
    return render.render("login.html", error=None, standalone=True,
                         username="")


@router.get("/reset-help", response_class=HTMLResponse)
def reset_help(request: Request):
    from app.web import render
    return render.render("reset_help.html", standalone=True, user=None)


@router.post("/login")
def login_submit(request: Request, username: str = Form("admin"),
                 password: str = Form("")):
    from app.web import render
    cfg = request.app.state.cfg
    ip = request.client.host if request.client else "unknown"
    if not request.app.state.limiter.allow(ip):
        from app.api.errors import ApiError
        raise ApiError(429, "rate_limited", "登录尝试过于频繁，请稍后再试")

    conn = db.connect(cfg.db_path)
    try:
        user = user_service.authenticate(conn, username, password)
    finally:
        conn.close()
    if user is None:
        return HTMLResponse(
            render.render("login.html", error="账号或密码不正确",
                          standalone=True, username=username),
            status_code=401,
        )
    token = make_token(cfg.cookie_secret,
                       int(time.time()) + SESSION_SECONDS,
                       user["id"], user["token_version"])
    resp = RedirectResponse("/", status_code=302)
    resp.set_cookie(COOKIE_NAME, token, httponly=True,
                    samesite="lax", max_age=SESSION_SECONDS)
    return resp


@router.get("/api/me")
def me(request: Request):
    user = request.state.user
    return {"id": user["id"], "username": user["username"],
            "role": user["role"]}


@router.post("/logout")
def logout():
    resp = RedirectResponse("/login", status_code=302)
    resp.delete_cookie(COOKIE_NAME)
    return resp
