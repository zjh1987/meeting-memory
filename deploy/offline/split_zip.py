"""把大文件切分为 GitHub Release 可上传的分卷（默认 1.9 GB）。

用法：
    python deploy/offline/split_zip.py dist/meeting-memory-offline-windows-x64.zip
"""

import argparse
from pathlib import Path

DEFAULT_SIZE = 1_900_000_000
CHUNK = 8 * 1024 * 1024


def main() -> int:
    parser = argparse.ArgumentParser(description="切分大文件为分卷")
    parser.add_argument("file", help="待切分的文件")
    parser.add_argument("--size", type=int, default=DEFAULT_SIZE,
                        help="单卷字节数，默认 1.9 GB")
    args = parser.parse_args()

    src = Path(args.file)
    if not src.is_file():
        print(f"文件不存在：{src}")
        return 1
    for old in src.parent.glob(src.name + ".part*"):
        old.unlink()

    index = 0
    with src.open("rb") as fh:
        while True:
            part = src.with_name(f"{src.name}.part{index + 1}")
            remaining = args.size
            with part.open("wb") as out:
                while remaining > 0:
                    chunk = fh.read(min(CHUNK, remaining))
                    if not chunk:
                        break
                    out.write(chunk)
                    remaining -= len(chunk)
            if part.stat().st_size == 0:
                part.unlink()
                break
            index += 1
            print(f"{part.name} {part.stat().st_size}")
    print(f"共 {index} 卷，原始大小 {src.stat().st_size}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
