"""纪要生成：统一 schema、强制引用、超长文本分块汇总。"""

import json

from app.config import Config
from app.providers import build_llm

REQUIRED_KEYS = ("summary", "topics", "decisions", "actions", "open_issues", "people")
CHUNK_THRESHOLD = 24000
CHUNK_SIZE = 8000
CHUNK_OVERLAP = 300

SYSTEM_PROMPT = """你是会议纪要助手。只依据给定的逐字稿整理，不得补充逐字稿中没有的事实。
输出严格 JSON，顶层字段固定为：
summary(string)、topics(list)、decisions(list)、actions(list)、open_issues(list)、people(list)。
topics 每条：{"title": str, "points": [str], "segment_ids": [int]}。
decisions 每条：{"text": str, "quote": str, "segment_ids": [int]}。
actions 每条：{"owner": str, "task": str, "due": str, "quote": str, "segment_ids": [int]}。
open_issues 每条：{"text": str, "reason": str, "quote": str, "segment_ids": [int]}。
所有 decisions/actions/open_issues 必须给出逐字稿原文 quote 与对应 segment_ids；
无法确定的信息写“待定”或“待指定”，不得编造。只输出 JSON，不要解释。"""

TEMPLATE_HINTS = {
    "standard": "\n模板：常规会议，均衡输出全部字段。",
    "discussion": "\n模板：座谈交流，重点提炼各方观点与 people，弱化决策。",
    "report": "\n模板：工作汇报，重点提炼进展、问题与下一步，弱化决策。",
}


class MinutesValidationError(Exception):
    pass


def _timestamp(seconds) -> str:
    total = int(float(seconds))
    return f"{total // 3600:02d}:{total % 3600 // 60:02d}:{total % 60:02d}"


def build_user_prompt(segments: list[dict]) -> str:
    lines = [f"[#{s['idx']}] {_timestamp(s['start'])} {s['speaker']} {s['text']}"
             for s in segments]
    return "以下是会议逐字稿，请生成纪要：\n" + "\n".join(lines)


def validate_minutes(data: dict, segment_count: int) -> dict:
    if not isinstance(data, dict):
        raise MinutesValidationError("输出不是 JSON 对象")
    summary = data.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise MinutesValidationError("summary 为空")
    topics = data.get("topics")
    if not isinstance(topics, list) or not topics:
        raise MinutesValidationError("topics 为空")
    for key in ("decisions", "actions", "open_issues"):
        items = data.get(key, [])
        if not isinstance(items, list):
            raise MinutesValidationError(f"{key} 不是数组")
        for item in items:
            if not str(item.get("quote") or "").strip():
                raise MinutesValidationError(f"{key} 存在空 quote")
            ids = item.get("segment_ids") or []
            if not ids or not all(isinstance(i, int) and 0 <= i < segment_count for i in ids):
                raise MinutesValidationError(f"{key} 的 segment_ids 非法")
    for action in data.get("actions", []):
        if not str(action.get("task") or "").strip():
            raise MinutesValidationError("actions 存在空 task")
        if not str(action.get("owner") or "").strip():
            action["owner"] = "待指定"
    for decision in data.get("decisions", []):
        if not str(decision.get("text") or "").strip():
            raise MinutesValidationError("decisions 存在空 text")
    data.setdefault("people", [])
    return {key: data[key] for key in REQUIRED_KEYS}


def chunk_segments(segments: list[dict], max_chars: int = CHUNK_SIZE,
                   overlap_chars: int = CHUNK_OVERLAP) -> list[list[dict]]:
    chunks: list[list[dict]] = []
    current: list[dict] = []
    length = 0
    for segment in segments:
        size = len(segment["text"])
        if current and length + size > max_chars:
            chunks.append(current)
            tail: list[dict] = []
            tail_len = 0
            for item in reversed(current):
                tail.insert(0, item)
                tail_len += len(item["text"])
                if tail_len >= overlap_chars:
                    break
            current = tail
            length = tail_len
        current.append(segment)
        length += size
    if current:
        chunks.append(current)
    return chunks


def merge_parts(parts: list[dict]) -> dict:
    merged = {key: [] for key in REQUIRED_KEYS}
    merged["summary"] = ""
    seen: set[str] = set()
    summaries: list[str] = []
    for part in parts:
        if part.get("summary"):
            summaries.append(part["summary"])
        for key in ("topics", "decisions", "actions", "open_issues", "people"):
            for item in part.get(key, []):
                signature = json.dumps(item, ensure_ascii=False, sort_keys=True)
                if signature in seen:
                    continue
                seen.add(signature)
                merged[key].append(item)
    merged["summary"] = "；".join(summaries)[:1000]
    return merged


def _request_valid(provider, segments: list[dict], template_key: str,
                   total_count: int) -> dict:
    user = build_user_prompt(segments) + TEMPLATE_HINTS.get(template_key, "")
    last_error = None
    for _ in range(2):
        data = provider.complete_json(SYSTEM_PROMPT, user)
        try:
            return validate_minutes(data, total_count)
        except MinutesValidationError as exc:
            last_error = exc
            user += f"\n\n上次输出不合法：{exc}。请修正后只输出 JSON。"
    raise last_error


def generate(cfg: Config, segments: list[dict], template_key: str = "standard") -> dict:
    provider = build_llm(cfg)
    total_chars = sum(len(s["text"]) for s in segments)
    chunks = [segments] if total_chars <= CHUNK_THRESHOLD else chunk_segments(segments)
    parts = [_request_valid(provider, chunk, template_key, len(segments))
             for chunk in chunks]
    data = parts[0] if len(parts) == 1 else merge_parts(parts)
    return validate_minutes(data, len(segments))
