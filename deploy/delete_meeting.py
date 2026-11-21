"""按 uid 删除会议：数据库记录、音频、静态归档，并刷新索引。"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def delete(cfg, uid: str) -> int:
    from app.services.meetings import delete_meeting
    ok, message = delete_meeting(cfg, uid)
    print(message)
    return 0 if ok else 1


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
