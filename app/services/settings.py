"""运行时设置与可定制纪要模板。

设置优先读数据库，未保存过则回落到 .env 的 Config 默认值。
"""

import json
import re
from datetime import datetime
from pathlib import Path

from app.config import Config

SECTION_KEYS = ("summary", "topics", "decisions", "actions", "open_issues", "people")
TEMPLATE_KEY = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
MAX_DURATION_DEFAULT_MIN = 360


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _raw(conn) -> dict[str, str]:
    try:
        rows = conn.execute("SELECT key, value FROM app_setting").fetchall()
    except Exception:
        return {}
    return {row["key"]: row["value"] for row in rows}


def _put(conn, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO app_setting (key, value, updated_at) VALUES (?,?,?)"
        " ON CONFLICT(key) DO UPDATE SET value=excluded.value,"
        " updated_at=excluded.updated_at",
        (key, value, _now()),
    )


def llm_settings(cfg: Config, conn) -> dict:
    raw = _raw(conn)
    return {
        "provider": raw.get("llm.provider", cfg.llm_provider),
        "base_url": raw.get("llm.base_url", cfg.llm_base_url),
        "api_key": raw.get("llm.api_key", cfg.llm_api_key),
        "model": raw.get("llm.model", cfg.llm_model),
        "temperature": float(raw.get("llm.temperature", "0.1")),
    }


def asr_settings(cfg: Config, conn) -> dict:
    raw = _raw(conn)
    return {
        "backend": raw.get("asr.backend", cfg.asr_backend),
        "model_dir": raw.get("asr.model_dir", str(cfg.funasr_model_dir)),
        "device": raw.get("asr.device", cfg.funasr_device),
        "speaker_threshold": float(
            raw.get("asr.speaker_threshold", str(cfg.speaker_threshold))),
        "max_duration_min": int(
            raw.get("asr.max_duration_min", str(MAX_DURATION_DEFAULT_MIN))),
    }


def save_llm(conn, data: dict) -> dict:
    provider = str(data.get("provider", "openai")).strip()
    if provider not in {"openai", "mock"}:
        raise ValueError("LLM 提供方只支持 openai / mock")
    base_url = str(data.get("base_url", "")).strip().rstrip("/")
    model = str(data.get("model", "")).strip()
    api_key = str(data.get("api_key", "")).strip()
    try:
        temperature = float(data.get("temperature", 0.1))
    except (TypeError, ValueError) as exc:
        raise ValueError("temperature 必须是数字") from exc
    if not 0 <= temperature <= 2:
        raise ValueError("temperature 必须在 0 到 2 之间")
    if provider == "openai":
        if not base_url.startswith(("http://", "https://")):
            raise ValueError("Base URL 必须以 http:// 或 https:// 开头")
        if not model:
            raise ValueError("必须填写模型名称")
    _put(conn, "llm.provider", provider)
    _put(conn, "llm.base_url", base_url)
    _put(conn, "llm.model", model)
    _put(conn, "llm.api_key", api_key)
    _put(conn, "llm.temperature", str(temperature))
    return {"provider": provider, "base_url": base_url, "model": model}
def save_asr(conn, data: dict) -> dict:
    backend = str(data.get("backend", "funasr")).strip()
    if backend not in {"funasr", "mock"}:
        raise ValueError("ASR 后端只支持 funasr / mock")
    model_dir = str(data.get("model_dir", "")).strip()
    device = str(data.get("device", "cuda:0")).strip() or "cuda:0"
    try:
        threshold = float(data.get("speaker_threshold", 0.75))
        max_duration = int(data.get("max_duration_min", MAX_DURATION_DEFAULT_MIN))
    except (TypeError, ValueError) as exc:
        raise ValueError("说话人阈值或最长时长格式不正确") from exc
    if not 0 <= threshold <= 1:
        raise ValueError("说话人阈值必须在 0 到 1 之间")
    if max_duration < 0:
        raise ValueError("最长时长不能为负数（0 表示不限制）")
    if not model_dir:
        raise ValueError("模型目录不能为空")
    if backend == "funasr" and not Path(model_dir).exists():
        raise ValueError(f"模型目录不存在：{model_dir}")
    _put(conn, "asr.backend", backend)
    _put(conn, "asr.model_dir", model_dir)
    _put(conn, "asr.device", device)
    _put(conn, "asr.speaker_threshold", str(threshold))
    _put(conn, "asr.max_duration_min", str(max_duration))
    return {"backend": backend, "device": device}


def relation_settings(conn) -> dict:
    """跨会议关联配置：只影响本地规则匹配，不进入大模型 prompt。"""
    raw = _raw(conn)
    return {
        "enabled": raw.get("relations.enabled", "1") not in {"0", "false", "False"},
        "window_days": int(raw.get("relations.window_days", "180")),
        "max_previous": int(raw.get("relations.max_previous", "10")),
        "topic_threshold": float(raw.get("relations.topic_threshold", "0.6")),
        "task_threshold": float(raw.get("relations.task_threshold", "0.5")),
        "hint": raw.get("relations.hint", ""),
    }


def save_relations(conn, data: dict) -> dict:
    enabled = 1 if data.get("enabled", True) else 0
    try:
        window_days = int(data.get("window_days", 180))
        max_previous = int(data.get("max_previous", 10))
        topic_threshold = float(data.get("topic_threshold", 0.6))
        task_threshold = float(data.get("task_threshold", 0.5))
    except (TypeError, ValueError) as exc:
        raise ValueError("关联设置必须是数字") from exc
    if not 0 <= window_days <= 3650:
        raise ValueError("回看天数必须在 0 到 3650 之间（0 表示不限）")
    if not 1 <= max_previous <= 50:
        raise ValueError("关联会议数必须在 1 到 50 之间")
    for label, value in (("议题阈值", topic_threshold), ("待办阈值", task_threshold)):
        if not 0 <= value <= 1:
            raise ValueError(f"{label}必须在 0 到 1 之间")
    hint = str(data.get("hint", "")).strip()
    if len(hint) > 2000:
        raise ValueError("关联提示词不能超过 2000 个字符")
    _put(conn, "relations.enabled", str(enabled))
    _put(conn, "relations.window_days", str(window_days))
    _put(conn, "relations.max_previous", str(max_previous))
    _put(conn, "relations.topic_threshold", str(topic_threshold))
    _put(conn, "relations.task_threshold", str(task_threshold))
    _put(conn, "relations.hint", hint)
    return relation_settings(conn)


def list_templates(conn) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM minute_template ORDER BY sort_order, key").fetchall()
    return [_template_dict(row) for row in rows]


def _template_dict(row) -> dict:
    return {
        "key": row["key"],
        "name": row["name"],
        "description": row["description"],
        "scene": row["scene"],
        "sections": json.loads(row["sections"]),
        "custom_sections": json.loads(row["custom_sections"] or "[]"),
        "hint": row["hint"],
        "builtin": bool(row["builtin"]),
        "sort_order": row["sort_order"],
    }


def default_template_key(conn) -> str:
    row = conn.execute(
        "SELECT key FROM minute_template ORDER BY sort_order, key LIMIT 1"
    ).fetchone()
    return row["key"] if row else "standard"


def get_template(conn, key: str) -> dict:
    row = None
    if key:
        row = conn.execute("SELECT * FROM minute_template WHERE key=?",
                           (key,)).fetchone()
    if row is None:
        row = conn.execute(
            "SELECT * FROM minute_template ORDER BY sort_order, key LIMIT 1"
        ).fetchone()
    if row is None:
        return {"key": "standard", "name": "常规会议", "hint": "",
                "description": "", "scene": "常规", "custom_sections": [],
                "sections": list(SECTION_KEYS), "sort_order": 0}
    return _template_dict(row)


def _clean_custom_sections(raw) -> list[dict]:
    if raw is None:
        raw = []
    if not isinstance(raw, list):
        raise ValueError("自定义模块必须是数组")
    if len(raw) > 8:
        raise ValueError("自定义模块最多 8 个")
    result = []
    seen = set()
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("自定义模块格式不正确")
        key = str(item.get("key", "")).strip()
        title = str(item.get("title", "")).strip()
        instruction = str(item.get("instruction", "")).strip()
        if not TEMPLATE_KEY.fullmatch(key):
            raise ValueError("自定义模块标识只能使用小写字母、数字、下划线和减号")
        if not title:
            raise ValueError("自定义模块标题不能为空")
        if key in seen:
            raise ValueError(f"自定义模块标识重复：{key}")
        seen.add(key)
        result.append({"key": key, "title": title,
                       "instruction": instruction})
    return result


def save_template(conn, data: dict) -> dict:
    key = str(data.get("key", "")).strip()
    name = str(data.get("name", "")).strip()
    hint = str(data.get("hint", "")).strip()
    description = str(data.get("description", "")).strip()
    scene = str(data.get("scene", "")).strip() or "常规"
    sections = [s for s in data.get("sections", []) if s in SECTION_KEYS]
    custom_sections = _clean_custom_sections(data.get("custom_sections"))
    if not TEMPLATE_KEY.fullmatch(key):
        raise ValueError("模板标识只能使用小写字母、数字、下划线和减号")
    if not name:
        raise ValueError("模板名称不能为空")
    if not sections:
        raise ValueError("至少选择一个展示模块")
    row = conn.execute("SELECT builtin FROM minute_template WHERE key=?",
                       (key,)).fetchone()
    if row and row["builtin"]:
        conn.execute(
            "UPDATE minute_template SET name=?, sections=?, hint=?,"
            " description=?, scene=?, custom_sections=?, updated_at=?"
            " WHERE key=?",
            (name, json.dumps(sections), hint, description, scene,
             json.dumps(custom_sections, ensure_ascii=False), _now(), key),
        )
    else:
        conn.execute(
            "INSERT INTO minute_template (key, name, sections, hint, builtin,"
            " description, scene, custom_sections, sort_order, updated_at)"
            " VALUES (?,?,?,?,0,?,?,?,"
            " COALESCE((SELECT MAX(sort_order)+10 FROM minute_template),100),?)"
            " ON CONFLICT(key) DO UPDATE SET name=excluded.name,"
            " sections=excluded.sections, hint=excluded.hint,"
            " description=excluded.description, scene=excluded.scene,"
            " custom_sections=excluded.custom_sections,"
            " updated_at=excluded.updated_at",
            (key, name, json.dumps(sections), hint, description, scene,
             json.dumps(custom_sections, ensure_ascii=False), _now()),
        )
    return get_template(conn, key)


def move_template(conn, key: str, direction: str) -> list[dict]:
    if direction not in {"up", "down"}:
        raise ValueError("排序方向只支持 up / down")
    rows = conn.execute(
        "SELECT key FROM minute_template ORDER BY sort_order, key").fetchall()
    keys = [row["key"] for row in rows]
    if key not in keys:
        raise ValueError("模板不存在")
    index = keys.index(key)
    target = index - 1 if direction == "up" else index + 1
    if target < 0 or target >= len(keys):
        return list_templates(conn)
    keys[index], keys[target] = keys[target], keys[index]
    conn.execute("BEGIN")
    try:
        for position, item_key in enumerate(keys, start=1):
            conn.execute(
                "UPDATE minute_template SET sort_order=?, updated_at=?"
                " WHERE key=?",
                (position * 10, _now(), item_key),
            )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return list_templates(conn)


def delete_template(conn, key: str) -> None:
    row = conn.execute("SELECT builtin FROM minute_template WHERE key=?",
                       (key,)).fetchone()
    if row is None:
        raise ValueError("模板不存在")
    if row["builtin"]:
        raise ValueError("内置模板不能删除")
    used = conn.execute("SELECT COUNT(*) AS n FROM meeting WHERE template_key=?",
                        (key,)).fetchone()["n"]
    if used:
        raise ValueError(f"仍有 {used} 场会议使用该模板，不能删除")
    conn.execute("DELETE FROM minute_template WHERE key=?", (key,))
