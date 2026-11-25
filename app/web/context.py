import json

from app.core import state
from app.services import settings as settings_service
from app.storage import action_repo, relation_repo


def failure_hint(meeting: dict) -> str:
    """把技术错误码翻译成用户能理解、可行动的提示。"""
    code = meeting.get("error_code") or ""
    message = meeting.get("error_msg") or ""
    lower = message.lower()
    if code == "audio_too_long":
        return ("录音时长超过服务器设置的转写上限。请缩短单次录音，"
                "或联系管理员调整 ASR 最长时长。")
    if code == "file_missing":
        return "服务器上找不到原始音频文件，请重新上传。"
    if code == "asr_unavailable":
        if ("torch.float32" in message or "cuda" in lower
                or "说话人分离" in message):
            return ("长录音的说话人分离阶段失败：FunASR 与当前 NumPy/Torch "
                    "版本不兼容。录音已保留，管理员升级服务端后可直接重试。")
        if "out of memory" in lower or "显存" in message:
            return "GPU 显存不足。建议缩短单场录音，或升级显卡后重试。"
        return ("语音识别服务异常。录音已保留，管理员可直接重试；"
                "如果反复失败，请检查 GPU、模型文件和服务端日志。")
    if code.startswith("llm_") or code == "minutes_failed":
        return ("转写已完成，但纪要生成失败。请联系管理员重新生成，"
                "或检查大模型配置后重试。")
    if code == "relation_failed":
        return "纪要已生成，但关联归档失败；可查看服务端日志后重新归档。"
    if code == "worker_timeout":
        return "处理超时，任务已自动重试。若仍然失败，建议缩短录音或检查服务器负载。"
    if code == "internal":
        return "服务端处理异常，录音已保留，可直接重试并查看服务端日志。"
    return "处理未完成，录音已保留，可直接重试。"


def build_context(conn, meeting: dict, user: dict | None = None) -> dict:
    minutes = json.loads(meeting["minutes"]) if meeting["minutes"] else {}
    transcript = json.loads(meeting["transcript"]) if meeting["transcript"] else []
    project = conn.execute(
        "SELECT name FROM project WHERE id=?", (meeting["project_id"],)
    ).fetchone()
    tmpl = settings_service.get_template(conn, meeting["template_key"])
    custom_minutes = {section.get("key"): section
                      for section in minutes.get("custom_sections", [])}
    owner_scope = None
    if user and user.get("role") != "admin":
        owner_scope = user["id"]
    return {
        "minutes": minutes,
        "transcript": transcript,
        "custom_minutes": custom_minutes,
        "actions": action_repo.list_for(conn, meeting["id"]),
        "relations": relation_repo.list_for(conn, meeting["id"], owner_scope),
        "tmpl": tmpl,
        "project_name": project["name"] if project else "未归类",
        "finished": meeting["status"] == "done",
        "processing": meeting["status"] not in {"done", "failed"},
        "failure_hint": failure_hint(meeting),
        "can_retry": state.can_retry(meeting),
    }
