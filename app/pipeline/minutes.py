"""纪要生成：统一 schema、强制引用、超长文本分块汇总。"""

import json
import re

from app.config import Config
from app.providers import build_llm

REQUIRED_KEYS = ("summary", "topics", "decisions", "actions", "open_issues", "people")
CHUNK_THRESHOLD = 24000
CHUNK_SIZE = 8000
CHUNK_OVERLAP = 300
TITLE_MAX = 20

_TITLE_DROP = re.compile(r"[\s\"'“”‘’《》〈〉【】\[\]（）()]+")
_TITLE_PUNCT = "，。；：、！？!?,;:-—…"
_TITLE_CLAUSE = re.compile(r"[。；;！!？?\n]")
_TITLE_PREFIX = re.compile(
    r"^(本次|这次|该次)?会议(主要)?(围绕|就|讨论了|研究了|听取了|对|认为)?")

SYSTEM_PROMPT = """你是资深会议秘书，服务于企事业单位管理层。你的任务是把逐字稿整理成
可执行、可追溯、无虚构的会议纪要。

必须遵守：
1. 只使用逐字稿中的信息，不得补充常识、猜测或外部知识。
2. decisions/actions/open_issues 每一条都必须给出逐字稿原文 quote 和对应 segment_ids；
   quote 必须是连续原文片段，不得改写。
3. 待办尽量补齐负责人和截止时间；原文没有就写“待指定”“待定”，不得编造。
4. 合并重复表述，保留关键数字、日期、人名与结论，删除寒暄和口头语。
5. 区分事实、观点与决定，不要把个人判断写成会议结论。
6. 输出严格 JSON，顶层字段固定为：
title(string，20 个汉字以内，概括会议主题，不要标点)、
summary(string)、topics(list)、decisions(list)、actions(list)、open_issues(list)、
people(list)、custom_sections(list)。
topics 每条：{"title": str, "points": [str], "segment_ids": [int]}。
decisions 每条：{"text": str, "quote": str, "segment_ids": [int]}。
actions 每条：{"owner": str, "task": str, "due": str, "quote": str, "segment_ids": [int]}。
open_issues 每条：{"text": str, "reason": str, "quote": str, "segment_ids": [int]}。
custom_sections 每条：{"key": str, "title": str, "items": [{"text": str, "quote": str,
"segment_ids": [int]}]}；没有要求时可输出空数组。
只输出 JSON，不要解释。"""

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


def _normalize_title(raw) -> str:
    text = _TITLE_DROP.sub("", str(raw or ""))
    return text.strip(_TITLE_PUNCT)


def clean_title(raw, limit: int = TITLE_MAX) -> str:
    text = _normalize_title(raw)
    if len(text) > limit:
        text = text[:limit].rstrip(_TITLE_PUNCT)
    return text


def derive_title(minutes: dict, fallback: str = "") -> str:
    """优先用模型给出的标题；缺失时从摘要首句提取，控制在 20 字以内。"""
    title = clean_title(minutes.get("title"))
    if title:
        return title
    summary = str(minutes.get("summary") or "").strip()
    for clause in _TITLE_CLAUSE.split(summary):
        candidate = _normalize_title(
            _TITLE_PREFIX.sub("", clause.strip()).strip("，,、：: "))
        if len(candidate) < 4:
            continue
        if len(candidate) <= TITLE_MAX:
            return candidate
        for part in re.split(r"[，,、：:；;]", candidate):
            part = _normalize_title(part)
            if 4 <= len(part) <= TITLE_MAX:
                return part
        return clean_title(candidate)
    cleaned = clean_title(summary)
    if cleaned:
        return cleaned
    for topic in minutes.get("topics") or []:
        cleaned = clean_title(topic.get("title"))
        if cleaned:
            return cleaned
    return clean_title(fallback)


def build_user_prompt(segments: list[dict], glossary: list[str] | None = None,
                      custom_sections: list[dict] | None = None) -> str:
    lines = [f"[#{s['idx']}] {_timestamp(s['start'])} {s['speaker']} {s['text']}"
             for s in segments]
    text = "以下是会议逐字稿，请生成纪要：\n" + "\n".join(lines)
    if glossary:
        words = "、".join(glossary[:50])
        text += f"\n\n专有名词参考（仅用于纠正识别错误，不得据此编造内容）：{words}"
    if custom_sections:
        spec = [{"key": s["key"], "title": s["title"],
                 "instruction": s.get("instruction", "")}
                for s in custom_sections]
        text += ("\n\n除固定字段外，请在 custom_sections 中按以下模块输出："
                 + json.dumps(spec, ensure_ascii=False)
                 + "。每个模块的 items 需给出 text 与 quote、segment_ids；"
                   "确实没有原文可引用时 quote 留空、segment_ids 为空数组。")
    return text


def validate_minutes(data: dict, segment_count: int) -> dict:
    if not isinstance(data, dict):
        raise MinutesValidationError("输出不是 JSON 对象")
    summary = data.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise MinutesValidationError("summary 为空")
    title = derive_title(data)
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

    custom_sections = data.get("custom_sections") or []
    if not isinstance(custom_sections, list):
        raise MinutesValidationError("custom_sections 不是数组")
    cleaned_sections = []
    for section in custom_sections:
        if not isinstance(section, dict):
            raise MinutesValidationError("custom_sections 项不是对象")
        key = str(section.get("key") or "").strip()
        title = str(section.get("title") or key).strip()
        items = []
        for item in section.get("items") or []:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            ids = item.get("segment_ids") or []
            if ids and not all(isinstance(i, int) and 0 <= i < segment_count
                               for i in ids):
                raise MinutesValidationError(
                    f"custom_sections 的 segment_ids 非法：{title}")
            items.append({"text": text,
                          "quote": str(item.get("quote") or "").strip(),
                          "segment_ids": ids})
        if title and items:
            cleaned_sections.append({"key": key or f"section_{len(cleaned_sections)}",
                                     "title": title, "items": items})

    result = {key: data[key] for key in REQUIRED_KEYS}
    result["title"] = title
    result["custom_sections"] = cleaned_sections
    return result


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
    merged["title"] = ""
    merged["summary"] = ""
    merged["custom_sections"] = []
    seen: set[str] = set()
    summaries: list[str] = []
    custom: dict[str, dict] = {}
    for part in parts:
        if not merged["title"] and part.get("title"):
            merged["title"] = part["title"]
        if part.get("summary"):
            summaries.append(part["summary"])
        for key in ("topics", "decisions", "actions", "open_issues", "people"):
            for item in part.get(key, []):
                signature = json.dumps(item, ensure_ascii=False, sort_keys=True)
                if signature in seen:
                    continue
                seen.add(signature)
                merged[key].append(item)
        for section in part.get("custom_sections", []):
            key = section.get("key") or section.get("title")
            target = custom.setdefault(key, {
                "key": section.get("key", "custom"),
                "title": section.get("title", ""),
                "items": [],
            })
            for item in section.get("items", []):
                signature = json.dumps(item, ensure_ascii=False, sort_keys=True)
                if signature in seen:
                    continue
                seen.add(signature)
                target["items"].append(item)
    merged["custom_sections"] = [s for s in custom.values() if s["items"]]
    merged["summary"] = "；".join(summaries)[:1000]
    return merged


def _request_valid(provider, segments: list[dict], hint: str,
                   total_count: int, glossary: list[str] | None = None,
                   custom_sections: list[dict] | None = None) -> dict:
    user = build_user_prompt(segments, glossary, custom_sections) + (hint or "")
    last_error = None
    for _ in range(2):
        data = provider.complete_json(SYSTEM_PROMPT, user)
        try:
            return validate_minutes(data, total_count)
        except MinutesValidationError as exc:
            last_error = exc
            user += f"\n\n上次输出不合法：{exc}。请修正后只输出 JSON。"
    raise last_error


def generate(cfg: Config, segments: list[dict], template_key: str = "standard",
             llm_settings: dict | None = None,
             hint: str | None = None,
             custom_sections: list[dict] | None = None,
             glossary: list[str] | None = None) -> dict:
    provider = build_llm(cfg, llm_settings)
    hint_text = TEMPLATE_HINTS.get(template_key, "") if hint is None else hint
    total_chars = sum(len(s["text"]) for s in segments)
    chunks = [segments] if total_chars <= CHUNK_THRESHOLD else chunk_segments(segments)
    parts = [_request_valid(provider, chunk, hint_text, len(segments),
                            glossary, custom_sections)
             for chunk in chunks]
    data = parts[0] if len(parts) == 1 else merge_parts(parts)
    return validate_minutes(data, len(segments))
