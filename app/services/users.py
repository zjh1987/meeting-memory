"""账号与密码：PBKDF2 哈希、角色校验、管理员初始化。"""

import hashlib
import hmac
import os
import re
from datetime import datetime

from app.config import Config

ROLES = {"admin", "member"}
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{2,32}$")
ITERATIONS = 200_000


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt,
                                 ITERATIONS)
    return f"pbkdf2${ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, iterations, salt_hex, digest_hex = stored.split("$", 3)
    except ValueError:
        return False
    if scheme != "pbkdf2":
        return False
    salt = bytes.fromhex(salt_hex)
    expected = bytes.fromhex(digest_hex)
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt,
                                 int(iterations))
    return hmac.compare_digest(actual, expected)


def ensure_admin(cfg: Config, conn) -> None:
    count = conn.execute("SELECT COUNT(*) AS n FROM app_user").fetchone()["n"]
    if count:
        return
    conn.execute(
        "INSERT INTO app_user (username, password_hash, display_name, role,"
        " token_version, created_at, updated_at) VALUES (?,?,?,?,0,?,?)",
        ("admin", hash_password(cfg.app_password), "管理员", "admin",
         _now(), _now()),
    )


def get_user(conn, user_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM app_user WHERE id=?", (user_id,)).fetchone()
    if row is None:
        return None
    return {
        "id": row["id"],
        "username": row["username"],
        "display_name": row["display_name"],
        "role": row["role"],
        "token_version": row["token_version"],
        "created_at": row["created_at"],
    }


def authenticate(conn, username: str, password: str) -> dict | None:
    row = conn.execute("SELECT * FROM app_user WHERE username=?",
                       (username.strip(),)).fetchone()
    if row is None or not verify_password(password, row["password_hash"]):
        return None
    return get_user(conn, row["id"])


def list_users(conn) -> list[dict]:
    rows = conn.execute(
        "SELECT id, username, display_name, role, created_at FROM app_user"
        " ORDER BY id").fetchall()
    return [dict(row) for row in rows]


def _clean_username(value: str) -> str:
    username = value.strip()
    if not USERNAME_PATTERN.fullmatch(username):
        raise ValueError("账号需为 2-32 位字母、数字、点、下划线或减号")
    return username


def _clean_password(value: str) -> str:
    if len(value or "") < 8:
        raise ValueError("密码至少 8 位")
    return value


def _admin_count(conn) -> int:
    return conn.execute(
        "SELECT COUNT(*) AS n FROM app_user WHERE role='admin'"
    ).fetchone()["n"]


def create_user(conn, data: dict) -> dict:
    username = _clean_username(str(data.get("username", "")))
    password = _clean_password(str(data.get("password", "")))
    role = str(data.get("role", "member"))
    if role not in ROLES:
        raise ValueError("角色只支持 admin / member")
    display_name = str(data.get("display_name", "")).strip() or username
    try:
        conn.execute(
            "INSERT INTO app_user (username, password_hash, display_name, role,"
            " token_version, created_at, updated_at) VALUES (?,?,?,?,0,?,?)",
            (username, hash_password(password), display_name, role,
             _now(), _now()),
        )
    except Exception as exc:
        if "UNIQUE" in str(exc):
            raise ValueError("账号已存在") from exc
        raise
    row = conn.execute("SELECT id FROM app_user WHERE username=?",
                       (username,)).fetchone()
    return get_user(conn, row["id"])


def batch_create_users(conn, items) -> dict:
    if not isinstance(items, list) or not items:
        raise ValueError("请提供要导入的账号")
    if len(items) > 200:
        raise ValueError("单次最多导入 200 个账号")
    created = []
    failed = []
    for index, item in enumerate(items, start=2):
        username = ""
        try:
            if not isinstance(item, dict):
                raise ValueError("行格式不正确")
            username = str(item.get("username", "")).strip()
            created.append(create_user(conn, item))
        except Exception as exc:
            failed.append({"row": index, "username": username,
                           "error": str(exc)})
    return {"created": len(created), "failed": failed, "items": created}


def update_user(conn, user_id: int, data: dict) -> dict:
    user = get_user(conn, user_id)
    if user is None:
        raise LookupError("账号不存在")
    role = str(data.get("role", user["role"]))
    if role not in ROLES:
        raise ValueError("角色只支持 admin / member")
    if user["role"] == "admin" and role != "admin" and _admin_count(conn) <= 1:
        raise ValueError("至少保留一个管理员")
    display_name = str(data.get("display_name", user["display_name"])).strip() \
        or user["username"]
    conn.execute("UPDATE app_user SET display_name=?, role=?, updated_at=?"
                 " WHERE id=?", (display_name, role, _now(), user_id))
    password = str(data.get("password", ""))
    if password:
        conn.execute(
            "UPDATE app_user SET password_hash=?, token_version=token_version+1,"
            " updated_at=? WHERE id=?",
            (hash_password(_clean_password(password)), _now(), user_id),
        )
    return get_user(conn, user_id)


def delete_user(conn, user_id: int, current_user_id: int) -> None:
    user = get_user(conn, user_id)
    if user is None:
        raise LookupError("账号不存在")
    if user_id == current_user_id:
        raise ValueError("不能删除当前登录账号")
    if user["role"] == "admin" and _admin_count(conn) <= 1:
        raise ValueError("至少保留一个管理员")
    # 账号删除后，把其会议归到当前管理员，避免数据无主。
    conn.execute("UPDATE meeting SET owner_id=? WHERE owner_id=?",
                 (current_user_id, user_id))
    conn.execute("DELETE FROM app_user WHERE id=?", (user_id,))


def change_password(conn, user_id: int, old_password: str,
                    new_password: str) -> None:
    row = conn.execute("SELECT * FROM app_user WHERE id=?", (user_id,)).fetchone()
    if row is None:
        raise LookupError("账号不存在")
    if not verify_password(old_password, row["password_hash"]):
        raise ValueError("当前密码不正确")
    conn.execute(
        "UPDATE app_user SET password_hash=?,"
        " token_version=token_version+1, updated_at=? WHERE id=?",
        (hash_password(_clean_password(new_password)), _now(), user_id),
    )
