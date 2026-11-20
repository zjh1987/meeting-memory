"""按 uid 删除会议：数据库记录、音频、静态归档，并刷新索引。"""

import argparse
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def delete(cfg, uid: str) -> int:
    conn = sqlite3.connect(str(cfg.db_path))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM meeting WHERE uid=?", (uid,)).fetchone()
        if not row:
            print(f"未找到会议：{uid}")
            return 1
        meeting_id = row["id"]
        conn.execute("DELETE FROM relation WHERE meeting_id=? OR target_id=?",
                     (meeting_id, meeting_id))
        conn.execute("DELETE FROM action_item WHERE meeting_id=?", (meeting_id,))
        conn.execute("DELETE FROM meeting WHERE id=?", (meeting_id,))
        conn.commit()
    finally:
        conn.close()

    for base in (cfg.archive_dir, cfg.ready_dir, cfg.inbox_dir):
        for path in base.glob(f"{uid}__*"):
            path.unlink(missing_ok=True)

    day = (row["recorded_at"] or "")[:10]
    try:
        datetime.strptime(day, "%Y-%m-%d")
    except ValueError:
        print(f"警告：recorded_at 非法（{row['recorded_at']!r}），跳过静态归档删除")
    else:
        shutil.rmtree(cfg.site_dir.joinpath(*day.split("-"), uid),
                       ignore_errors=True)

    from app.pipeline import archive
    archive.refresh_indices(cfg)
    print(f"已删除：{uid}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="删除指定会议及其归档")
    parser.add_argument("uid")
    args = parser.parse_args()
    from app.config import Config
    config = Config.from_env()
    problems = config.validate()
    if problems:
        print("配置错误：" + "；".join(problems))
        return 2
    return delete(config, args.uid)


if __name__ == "__main__":
    raise SystemExit(main())
