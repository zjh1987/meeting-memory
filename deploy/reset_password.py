"""在服务器本地重置账号密码（会同时使该账号所有会话失效）。

用法：
    python deploy/reset_password.py admin
    python deploy/reset_password.py admin --password 新密码
"""

import argparse
import getpass
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description="重置会议记忆账号密码")
    parser.add_argument("username", nargs="?", default="admin",
                        help="登录账号，默认 admin")
    parser.add_argument("--password", default="",
                        help="新密码；不填则交互输入")
    args = parser.parse_args()

    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")

    from app.config import Config
    from app.services import users as user_service
    from app.storage import db

    cfg = Config.from_env()
    db.init_db(cfg.db_path)
    conn = db.connect(cfg.db_path)
    try:
        user_service.ensure_admin(cfg, conn)
        row = conn.execute("SELECT id FROM app_user WHERE username=?",
                           (args.username,)).fetchone()
        if row is None:
            names = [r["username"] for r in
                     conn.execute("SELECT username FROM app_user ORDER BY id")]
            print(f"账号不存在：{args.username}")
            print("现有账号：" + "、".join(names))
            return 1

        password = args.password
        if not password:
            try:
                password = getpass.getpass("新密码（至少 8 位）：")
                confirm = getpass.getpass("再次输入新密码：")
            except EOFError:
                print("当前环境无法交互输入，请使用 --password 参数")
                return 2
            if password != confirm:
                print("两次输入不一致")
                return 2
        if len(password) < 8:
            print("密码至少 8 位")
            return 2

        conn.execute(
            "UPDATE app_user SET password_hash=?,"
            " token_version=token_version+1,"
            " updated_at=datetime('now','localtime') WHERE id=?",
            (user_service.hash_password(password), row["id"]),
        )
    finally:
        conn.close()
    print(f"已重置 {args.username} 的密码，该账号需要重新登录。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
