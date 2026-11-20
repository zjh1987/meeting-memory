"""ASR 与纪要生成的可替换实现。

默认 mock：不需要任何密钥，用内置样例把整条链路跑通。
配置后切到真实接口：
    set ASR_PROVIDER=openai & set LLM_PROVIDER=openai & set OPENAI_API_KEY=sk-xxx
真实场景建议换成带说话人分离的云 ASR（阿里云/腾讯云）或本地 FunASR，
因为它们支持热词表，对单位名、项目代号、人名的识别率高得多。
"""

import json
import re
import time

import config

# ---------------------------------------------------------------- mock 数据

_MOCK_SCRIPT = [
    ("王总", "今天主要过一下三季度的进度，顺便把年底前要落的几件事定下来。"),
    ("李工", "系统这边三季度的功能都上完了，还有一个数据同步的问题没有解决。"),
    ("王总", "数据同步卡在哪里了？"),
    ("李工", "对方接口不稳定，高峰期会丢数据。"),
    ("张敏", "这个问题我们提过两次了，对方一直没给排期。"),
    ("王总", "这个不能再拖了，决定月底前走一次高层协调，张敏负责对接。"),
    ("张敏", "好的，我下周先把问题清单整理出来。"),
    ("李工", "另外测试环境下周可以交付，需要提前申请资源。"),
    ("王总", "资源的事让运维配合，李工负责提申请。"),
    ("张敏", "座谈这块的预算还没定，要看四季度有没有调整。"),
    ("王总", "预算先待定，回头再看。"),
    ("李工", "还有一个想法，能不能把会议记录自动归档，省得每次翻聊天记录。"),
    ("王总", "这个可以研究一下，先做个原型看看效果。"),
    ("张敏", "我这边可以配合出需求。"),
    ("王总", "行，今天就到这里，散会。"),
]


def _mock_segments() -> list[dict]:
    segments = []
    t = 0.0
    for speaker, text in _MOCK_SCRIPT:
        dur = max(3.0, len(text) * 0.28)
        segments.append({
            "start": round(t, 1),
            "end": round(t + dur, 1),
            "speaker": speaker,
            "text": text,
        })
        t += dur + 0.8
    return segments


# ---------------------------------------------------------------- ASR

def transcribe(audio_path: str) -> list[dict]:
    """返回 [{start, end, speaker, text}, ...]"""
    if config.ASR_PROVIDER == "openai" and config.OPENAI_API_KEY:
        return _openai_transcribe(audio_path)
    time.sleep(0.6)  # 让状态切换在页面上看得见
    return _mock_segments()


def _openai_transcribe(audio_path: str) -> list[dict]:
    import httpx

    with open(audio_path, "rb") as f:
        resp = httpx.post(
            f"{config.OPENAI_BASE_URL}/audio/transcriptions",
            headers={"Authorization": f"Bearer {config.OPENAI_API_KEY}"},
            files={"file": (audio_path, f, "application/octet-stream")},
            data={"model": config.ASR_MODEL, "response_format": "verbose_json"},
            timeout=900,
        )
    resp.raise_for_status()
    payload = resp.json()

    # 部分兼容接口会直接返回 segments；没有就按句切分兜底
    raw = payload.get("segments")
    if raw:
        return [{
            "start": float(s.get("start", 0)),
            "end": float(s.get("end", 0)),
            "speaker": s.get("speaker") or "说话人1",
            "text": (s.get("text") or "").strip(),
        } for s in raw if (s.get("text") or "").strip()]

    text = (payload.get("text") or "").strip()
    parts = [p.strip() for p in re.split(r"(?<=[。！？])", text) if p.strip()]
    return [{"start": float(i * 5), "end": float(i * 5 + 5),
             "speaker": "说话人1", "text": p} for i, p in enumerate(parts)]


# ---------------------------------------------------------------- 纪要生成

_DECISION = ("决定", "定了", "就这么", "结论", "拍板", "确定")
_ACTION = ("负责", "跟进", "下周", "月底", "之前", "提交", "整理", "对接", "推进", "配合")
_OPEN = ("待定", "再看看", "没定", "回头", "再说", "看情况")


def summarize(segments: list[dict], template_key: str = "standard") -> dict:
    if config.LLM_PROVIDER == "openai" and config.OPENAI_API_KEY:
        try:
            return _llm_summarize(segments, template_key)
        except Exception:
            pass  # 真实接口失败时退回规则版，保证链路不断
    time.sleep(0.4)
    return _mock_summarize(segments)


def _sentences(segments: list[dict]) -> list[dict]:
    out = []
    for seg in segments:
        for part in re.split(r"[。；！？!?;]", seg["text"]):
            part = part.strip()
            if len(part) >= 4:
                out.append({"speaker": seg["speaker"], "text": part, "start": seg["start"]})
    return out


def _mock_summarize(segments: list[dict]) -> dict:
    sents = _sentences(segments)

    decisions, actions, opens = [], [], []
    for s in sents:
        text = s["text"]
        if any(w in text for w in _DECISION):
            decisions.append({"text": text, "owner": s["speaker"], "quote": text})
        if any(w in text for w in _ACTION):
            actions.append({
                "owner": _guess_owner(text, s["speaker"]),
                "task": text,
                "due": _guess_due(text),
                "quote": text,
            })
        if any(w in text for w in _OPEN):
            opens.append(text)

    topics = []
    for i in range(0, len(sents), 4):
        chunk = sents[i:i + 4]
        if not chunk:
            continue
        topics.append({
            "title": chunk[0]["text"][:18],
            "points": [c["text"] for c in chunk],
        })

    people = []
    seen = {}
    for seg in segments:
        seen.setdefault(seg["speaker"], []).append(seg["text"])
    for name, lines in seen.items():
        people.append({"name": name, "stance": lines[0][:30]})

    summary = "；".join(s["text"] for s in sents[:2])
    return {
        "summary": summary[:120],
        "topics": topics[:5],
        "decisions": decisions[:5],
        "actions": actions[:8],
        "open_issues": opens[:4],
        "people": people[:6],
    }


def _guess_owner(text: str, default: str) -> str:
    m = re.search(r"([\u4e00-\u9fa5]{1,3})(负责|跟进|整理|对接|提交|配合)", text)
    return m.group(1) if m else default


def _guess_due(text: str) -> str:
    for w in ("下周", "月底", "本周", "周一", "周二", "周三", "周四", "周五"):
        if w in text:
            return w
    return ""


def _llm_summarize(segments: list[dict], template_key: str) -> dict:
    import httpx

    transcript = "\n".join(f"[{s['speaker']}] {s['text']}" for s in segments)
    prompt = (
        "你是会议纪要助手。请只输出 JSON，不要输出解释。\n"
        "结构：{\"summary\":\"\",\"topics\":[{\"title\":\"\",\"points\":[\"\"]}],"
        "\"decisions\":[{\"text\":\"\",\"owner\":\"\",\"quote\":\"\"}],"
        "\"actions\":[{\"owner\":\"\",\"task\":\"\",\"due\":\"\",\"quote\":\"\"}],"
        "\"open_issues\":[\"\"],\"people\":[{\"name\":\"\",\"stance\":\"\"}]}\n"
        "要求：quote 必须是原文片段；没有的字段返回空数组或空字符串，禁止编造。\n"
        f"会议类型：{template_key}\n\n转写全文：\n{transcript}"
    )
    resp = httpx.post(
        f"{config.OPENAI_BASE_URL}/chat/completions",
        headers={"Authorization": f"Bearer {config.OPENAI_API_KEY}"},
        json={
            "model": config.LLM_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        },
        timeout=300,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    data = json.loads(content)
    for key in ("topics", "decisions", "actions", "open_issues", "people"):
        data.setdefault(key, [])
    data.setdefault("summary", "")
    return data
