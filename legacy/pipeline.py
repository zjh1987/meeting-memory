"""采集与处理流水线。

链路：inbox 出现完整文件 -> 原子移动到 ready -> 写入会议记录(pending)
      -> worker 领取 -> ASR -> 纪要 -> 关联 -> 归档
"""

import json
import shutil
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path

import config
import providers
import render
import store

UID_SEP = "__"


# ---------------------------------------------------------------- 采集

def _split_name(stem: str) -> tuple[str, str]:
    if UID_SEP in stem:
        uid, title = stem.split(UID_SEP, 1)
        return uid, title
    return stem, stem


def harvest_once() -> int:
    """把 inbox 里的完整文件收进 ready。.part 一律跳过，这是原子的关键。"""
    count = 0
    for path in sorted(config.INBOX_DIR.iterdir()):
        if not path.is_file():
            continue
        if path.suffix.lower() not in config.AUDIO_SUFFIXES:
            continue  # .part 之类直接忽略

        uid, title = _split_name(path.stem)
        if store.get_meeting(uid):
            continue

        # 可选元数据旁挂文件：设备/手机上传时写入项目名
        project = config.DEFAULT_PROJECT
        meta_path = path.with_suffix(".json")
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                project = meta.get("project") or project
                title = meta.get("title") or title
            except (ValueError, OSError):
                pass
            meta_path.unlink(missing_ok=True)

        dest = config.READY_DIR / f"{path.stem}{path.suffix.lower()}"
        shutil.move(str(path), str(dest))  # 同盘移动，原子完成

        store.create_meeting(
            uid=uid,
            title=title,
            project=project,
            audio_path=str(dest),
            recorded_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )
        count += 1
    return count


def harvest_loop() -> None:
    while True:
        try:
            harvest_once()
        except Exception:
            traceback.print_exc()
        time.sleep(config.SCAN_INTERVAL)


# ---------------------------------------------------------------- 处理

def build_relations(meeting: dict, minutes: dict) -> list[dict]:
    """只做两条能拿原文举证的规则，不做"让模型随便联想"。"""
    relations = []
    prev_list = store.previous_in_project(meeting["project"], meeting["id"], limit=5)

    current_titles = [t.get("title", "") for t in minutes.get("topics", [])]

    for prev in prev_list:
        # 规则一：上次未完成的待办，这次没有看到落实
        open_items = store.open_actions(prev["id"])
        if open_items:
            relations.append({
                "target_id": prev["id"],
                "kind": "pending_carryover",
                "detail": f"上次还有 {len(open_items)} 条待办未见结论",
                "quote": open_items[0]["task"],
            })

        # 规则二：议题重复出现
        prev_minutes = json.loads(prev["minutes"]) if prev["minutes"] else {}
        prev_titles = [t.get("title", "") for t in prev_minutes.get("topics", [])]
        for cur in current_titles:
            if any(cur and cur in pt for pt in prev_titles if pt):
                relations.append({
                    "target_id": prev["id"],
                    "kind": "repeat_topic",
                    "detail": f"议题「{cur[:18]}」上次也讨论过",
                    "quote": cur,
                })
                break
    return relations


def process(meeting: dict) -> None:
    mid = meeting["id"]

    segments = providers.transcribe(meeting["audio_path"])
    store.save_transcript(mid, segments)

    store.set_status(mid, "minuting")
    minutes = providers.summarize(segments, meeting["template_key"])
    store.save_minutes(mid, minutes, meeting["template_key"])
    store.replace_actions(mid, minutes.get("actions", []))

    fresh = store.get_meeting(meeting["uid"])
    relations = build_relations(fresh, minutes)
    store.replace_relations(mid, relations)

    # 原音频归档，ready 目录保持干净
    audio = Path(meeting["audio_path"])
    if audio.exists():
        shutil.move(str(audio), str(config.ARCHIVE_DIR / audio.name))

    store.set_status(mid, "done")
    render.export_static(meeting["uid"])


def worker_loop() -> None:
    while True:
        meeting = None
        try:
            meeting = store.claim_next_pending()
            if not meeting:
                time.sleep(1.5)
                continue
            process(meeting)
        except Exception as exc:
            traceback.print_exc()
            if meeting:
                store.set_status(meeting["id"], "failed", str(exc)[:500])
        time.sleep(0.2)


def start() -> None:
    threading.Thread(target=harvest_loop, daemon=True).start()
    threading.Thread(target=worker_loop, daemon=True).start()
