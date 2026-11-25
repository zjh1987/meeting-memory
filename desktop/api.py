"""会议记忆服务端 API 客户端。"""

import os
from typing import Callable
from urllib.parse import urlsplit

import requests
import urllib3


class ApiError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.message = message
        self.status = status


def normalize_base(raw: str) -> str:
    value = (raw or "").strip()
    if not value:
        return ""
    if not value.lower().startswith(("http://", "https://")):
        value = "http://" + value
    return value.rstrip("/")


def friendly_network_error(error: Exception) -> str:
    text = str(error)
    lower = text.lower()
    if "timed out" in lower or "timeout" in lower:
        return "连接服务器超时，请检查地址、端口和网络。"
    if "connection refused" in lower:
        return "服务器拒绝连接，请确认服务已启动且端口正确。"
    if "name or service not known" in lower or "getaddrinfo" in lower:
        return "找不到服务器地址，请检查服务器 IP 或域名。"
    if "ssl" in lower or "certificate" in lower:
        return "HTTPS 证书校验失败。若服务器使用自签证书，请勾选“信任自签证书”。"
    if "network is unreachable" in lower:
        return "当前网络不可达，请确认电脑与服务器在同一网络。"
    return text or "网络请求失败"


class ApiClient:
    def __init__(self, base_url: str, trust_self_signed: bool = False):
        self.base = normalize_base(base_url)
        if not self.base:
            raise ApiError("服务器地址不能为空")
        self.host = urlsplit(self.base).hostname or ""
        self.session = requests.Session()
        self.session.verify = not trust_self_signed
        if trust_self_signed:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    def close(self) -> None:
        try:
            self.session.close()
        except Exception:
            pass

    def login(self, username: str, password: str) -> None:
        try:
            response = self.session.post(
                self.base + "/login",
                data={"username": username, "password": password},
                timeout=(8, 20),
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            raise ApiError(friendly_network_error(exc)) from exc
        if response.status_code == 401:
            raise ApiError("账号或密码不正确", 401)
        if response.status_code == 429:
            raise ApiError("登录尝试过于频繁，请稍后再试", 429)
        if response.status_code >= 400:
            raise ApiError(self._error_message(response), response.status_code)
        if not self.session.cookies.get("mm_session"):
            raise ApiError("登录失败：服务器没有返回会话")

    def me(self) -> dict:
        return self._get("/api/me")

    def projects(self) -> list[dict]:
        return self._get("/api/projects").get("items", [])

    def templates(self) -> list[dict]:
        return self._get("/api/templates").get("items", [])

    def status(self, uid: str) -> dict:
        return self._get(f"/api/meetings/{uid}/status")

    def upload(self, path: str, fields: dict,
               progress: Callable[[int], None] | None = None) -> dict:
        total = os.path.getsize(path)
        reader = _ProgressReader(path, total, progress)
        try:
            response = self.session.post(
                self.base + "/api/meetings",
                data={key: str(value) for key, value in fields.items()},
                files={"file": (os.path.basename(path), reader, "audio/wav")},
                timeout=(10, 7200),
            )
        except requests.RequestException as exc:
            raise ApiError(friendly_network_error(exc)) from exc
        finally:
            reader.close()
        if response.status_code == 401:
            raise ApiError("登录已过期，请重新登录", 401)
        if response.status_code >= 400:
            raise ApiError(self._error_message(response), response.status_code)
        try:
            data = response.json()
        except ValueError as exc:
            raise ApiError("服务器返回了无法识别的内容") from exc
        if not data.get("uid"):
            raise ApiError("上传失败：服务器没有返回会议编号")
        return data

    def _get(self, path: str) -> dict:
        try:
            response = self.session.get(self.base + path, timeout=(8, 30))
        except requests.RequestException as exc:
            raise ApiError(friendly_network_error(exc)) from exc
        if response.status_code == 401:
            raise ApiError("登录已过期，请重新登录", 401)
        if response.status_code >= 400:
            raise ApiError(self._error_message(response), response.status_code)
        try:
            return response.json()
        except ValueError as exc:
            raise ApiError("服务器返回了无法识别的内容") from exc

    def cookie(self) -> str:
        return self.session.cookies.get("mm_session") or ""

    def set_cookie(self, value: str, host: str) -> None:
        if value:
            self.session.cookies.set("mm_session", value, domain=host, path="/")

    @staticmethod
    def _error_message(response: requests.Response) -> str:
        try:
            data = response.json()
            message = (data.get("error") or {}).get("message")
            if message:
                return str(message)
        except ValueError:
            pass
        return f"服务器返回 {response.status_code}"


class _ProgressReader:
    """给 requests 提供可读的文件包装，同时回报上传进度。"""

    def __init__(self, path: str, total: int,
                 callback: Callable[[int], None] | None):
        self._file = open(path, "rb")
        self._total = max(total, 1)
        self._sent = 0
        self._callback = callback
        self._last = -1

    def __len__(self) -> int:
        return self._total

    def read(self, size: int = -1) -> bytes:
        chunk = self._file.read(size)
        if chunk:
            self._sent += len(chunk)
            percent = min(int(self._sent * 100 / self._total), 100)
            if percent != self._last:
                self._last = percent
                if self._callback:
                    self._callback(percent)
        return chunk

    def close(self) -> None:
        try:
            self._file.close()
        except Exception:
            pass
