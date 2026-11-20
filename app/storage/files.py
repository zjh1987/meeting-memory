"""采集文件的原子性保证：先写 .part，写完 fsync，最后 rename。"""

import hashlib
import json
import os
import re
import shutil
import uuid
from datetime import datetime
from pathlib import Path

AUDIO_SUFFIXES = {".m4a", ".mp3", ".wav", ".opus", ".aac", ".amr", ".flac"}


def sanitize_title(raw: str, fallback: str = "未命名会议") -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\r\n\t]', "-", raw or "").strip(" .")
    return (cleaned or fallback)[:80]


def new_uid(now: datetime | None = None) -> str:
    moment = now or datetime.now()
    return moment.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]


def free_gb(path: Path) -> float:
    return shutil.disk_usage(str(path)).free / (1024 ** 3)


def save_stream(src, inbox: Path, uid: str, title: str, ext: str,
                meta: dict, max_bytes: int | None = None):
    """从文件对象读入，返回 (最终路径, 字节数, sha256)。失败时清理残片。"""
    # 文件名整体（含 uid、__、扩展名与 .part）限制在 200 字节内，避免超出
    # ext4 的 255 字节上限；按 UTF-8 字节裁剪，不破坏多字节字符。
    budget = 200 - len(uid.encode()) - len("__") - len(ext.encode()) - len(".part")
    raw = title.encode("utf-8")
    if len(raw) > budget:
        title = raw[:max(budget, 0)].decode("utf-8", "ignore")
    stem = f"{uid}__{title}"
    part = inbox / f"{stem}{ext}.part"
    meta_path = inbox / f"{stem}.json"
    digest = hashlib.sha256()
    total = 0
    try:
        with part.open("wb") as out:
            while True:
                chunk = src.read(1 << 20)
                if not chunk:
                    break
                total += len(chunk)
                if max_bytes is not None and total > max_bytes:
                    raise ValueError("文件超过大小限制")
                digest.update(chunk)
                out.write(chunk)
            out.flush()
            os.fsync(out.fileno())
        meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        final = inbox / f"{stem}{ext}"
        part.rename(final)
        return final, total, digest.hexdigest()
    except Exception:
        part.unlink(missing_ok=True)
        meta_path.unlink(missing_ok=True)
        raise


def split_stem(stem: str) -> tuple[str, str]:
    if "__" in stem:
        uid, title = stem.split("__", 1)
        return uid, title
    return stem, stem


def move_to_ready(path: Path, ready_dir: Path) -> Path:
    dest = ready_dir / path.name
    shutil.move(str(path), str(dest))
    return dest
