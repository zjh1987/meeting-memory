"""会议状态机。所有状态推进都必须先过 can_transition。"""

STATUS_LABELS = {
    "uploading": "接收中",
    "pending": "排队中",
    "transcribing": "转写中",
    "minuting": "生成纪要中",
    "relating": "归档中",
    "done": "已完成",
    "failed": "处理失败",
}

PROCESSING = ("transcribing", "minuting", "relating")

_ALLOWED = {
    ("uploading", "pending"),
    ("uploading", "failed"),
    ("pending", "transcribing"),
    ("pending", "failed"),
    ("transcribing", "minuting"),
    ("transcribing", "relating"),
    ("transcribing", "pending"),
    ("transcribing", "failed"),
    ("minuting", "relating"),
    ("minuting", "done"),
    ("minuting", "pending"),
    ("minuting", "failed"),
    ("relating", "done"),
    ("relating", "pending"),
    ("failed", "pending"),
    ("done", "failed"),
    ("done", "pending"),
}


def can_transition(src: str, dst: str) -> bool:
    return (src, dst) in _ALLOWED


def resume_stage(transcript: str | None, minutes: str | None) -> str:
    """根据已有产物决定从哪一步继续，避免重试时重复调用 ASR。"""
    if not transcript:
        return "transcribe"
    if not minutes:
        return "minutes"
    return "relations"


def can_retry(meeting: dict) -> bool:
    status = meeting["status"]
    if status == "failed":
        return True
    return status == "done" and not meeting.get("minutes")
