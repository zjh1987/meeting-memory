import hashlib
import hmac
import time
from collections import defaultdict, deque

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

router = APIRouter()
COOKIE_NAME = "mm_session"
SESSION_SECONDS = 7 * 86400


def make_token(secret: str, expires_ts: int) -> str:
    payload = str(expires_ts)
    sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def verify_token(secret: str, token: str | None, now_ts: int | None = None) -> bool:
    if not token or "." not in token:
        return False
    payload, sig = token.split(".", 1)
    expected = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return False
    try:
        expires = int(payload)
    except ValueError:
        return False
    return expires > (int(time.time()) if now_ts is None else now_ts)


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
    return render.render("login.html", error=None, standalone=True)


@router.post("/login")
def login_submit(request: Request, password: str = Form("")):
    cfg = request.app.state.cfg
    ip = request.client.host if request.client else "unknown"
    if not request.app.state.limiter.allow(ip):
        from app.api.errors import ApiError
        raise ApiError(429, "rate_limited", "登录尝试过于频繁，请稍后再试")
    if password != cfg.app_password:
        from app.web import render
        return HTMLResponse(
            render.render("login.html", error="口令不正确", standalone=True),
            status_code=401,
        )
    token = make_token(cfg.cookie_secret, int(time.time()) + SESSION_SECONDS)
    resp = RedirectResponse("/", status_code=302)
    resp.set_cookie(COOKIE_NAME, token, httponly=True,
                    samesite="lax", max_age=SESSION_SECONDS)
    return resp


@router.post("/logout")
def logout():
    resp = RedirectResponse("/login", status_code=302)
    resp.delete_cookie(COOKIE_NAME)
    return resp
