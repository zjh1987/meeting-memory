"""后台管理 API：LLM/ASR 设置、热词、纪要模板与会议管理。"""

import os
import time
from pathlib import Path

from fastapi import APIRouter, Body, Request

from app.api.errors import ApiError
from app.config import Config
from app.providers import build_llm
from app.providers.errors import ProviderError
from app.pipeline import archive
from app.services import meetings as meeting_service
from app.services import settings as settings_service
from app.services import users as user_service
from app.storage import db

router = APIRouter(prefix="/api/admin")

MODEL_LABELS = {
    "asr": "Paraformer-zh",
    "vad": "FSMN-VAD",
    "punc": "CT-Punc",
    "spk": "CAM++",
}


def mask_key(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 10:
        return "已配置"
    return f"{key[:3]}****{key[-4:]}"


def model_status(base: Path) -> list[dict]:
    result = []
    for key, label in MODEL_LABELS.items():
        folder = base / key
        files = [p for p in folder.glob("*") if p.is_file()] if folder.is_dir() else []
        size = sum(p.stat().st_size for p in files)
        ready = (folder / "config.yaml").exists() and any(
            p.suffix in {".pt", ".bin"} for p in files)
        result.append({
            "key": key,
            "label": label,
            "path": str(folder),
            "ready": ready,
            "size_mb": round(size / 1024 / 1024, 1),
            "files": len(files),
        })
    return result


def gpu_info() -> dict:
    try:
        import torch
        if torch.cuda.is_available():
            props = torch.cuda.get_device_properties(0)
            return {"available": True, "name": props.name,
                    "memory_mb": int(props.total_memory / 1024 / 1024)}
        return {"available": False, "name": "未检测到 CUDA", "memory_mb": 0}
    except Exception:
        return {"available": False, "name": "未安装 torch", "memory_mb": 0}


def _hotwords(cfg: Config) -> list[str]:
    try:
        return [line.strip() for line in
                cfg.hotword_file.read_text(encoding="utf-8").splitlines()
                if line.strip()]
    except OSError:
        return []


def _metrics(conn) -> dict:
    row = conn.execute(
        "SELECT COUNT(*) AS n, AVG(asr_seconds) AS avg_seconds,"
        " AVG(audio_seconds) AS avg_audio,"
        " AVG(CASE WHEN audio_seconds>0 THEN asr_seconds/audio_seconds END)"
        " AS avg_rtf FROM meeting WHERE asr_seconds IS NOT NULL"
    ).fetchone()
    return {
        "count": row["n"] or 0,
        "avg_seconds": round(row["avg_seconds"] or 0, 2),
        "avg_audio": round(row["avg_audio"] or 0, 1),
        "avg_rtf": round(row["avg_rtf"] or 0, 3),
    }


@router.get("/settings")
def get_settings(request: Request):
    cfg = request.app.state.cfg
    conn = db.connect(cfg.db_path)
    try:
        llm = settings_service.llm_settings(cfg, conn)
        asr = settings_service.asr_settings(cfg, conn)
        templates = settings_service.list_templates(conn)
        metrics = _metrics(conn)
    finally:
        conn.close()
    return {
        "llm": {**llm, "api_key": "", "has_key": bool(llm["api_key"]),
                "masked_key": mask_key(llm["api_key"])},
        "asr": {**asr,
                "models": model_status(Path(asr["model_dir"])),
                "gpu": gpu_info(),
                "metrics": metrics},
        "hotwords": _hotwords(cfg),
        "templates": templates,
    }


@router.post("/llm")
def save_llm(request: Request, payload: dict = Body(...)):
    cfg = request.app.state.cfg
    conn = db.connect(cfg.db_path)
    try:
        current = settings_service.llm_settings(cfg, conn)
        data = dict(payload)
        if data.get("clear_key"):
            data["api_key"] = ""
        elif not str(data.get("api_key") or "").strip():
            data["api_key"] = current["api_key"]
        settings_service.save_llm(conn, data)
        saved = settings_service.llm_settings(cfg, conn)
    except ValueError as exc:
        raise ApiError(400, "invalid_setting", str(exc)) from exc
    finally:
        conn.close()
    return {"ok": True, "model": saved["model"],
            "masked_key": mask_key(saved["api_key"])}


@router.post("/asr")
def save_asr(request: Request, payload: dict = Body(...)):
    cfg = request.app.state.cfg
    conn = db.connect(cfg.db_path)
    try:
        settings_service.save_asr(conn, payload)
        saved = settings_service.asr_settings(cfg, conn)
    except ValueError as exc:
        raise ApiError(400, "invalid_setting", str(exc)) from exc
    finally:
        conn.close()
    return {"ok": True, "asr": saved}


@router.post("/test-llm")
def test_llm(request: Request):
    cfg = request.app.state.cfg
    conn = db.connect(cfg.db_path)
    try:
        options = settings_service.llm_settings(cfg, conn)
    finally:
        conn.close()
    provider = build_llm(cfg, options)
    started = time.perf_counter()
    try:
        data = provider.complete_json(
            "你是连通性测试助手，只输出 JSON。",
            '请只输出 {"ok": true}，不要输出其他内容。')
    except ProviderError as exc:
        return {"ok": False, "error": f"{exc.code}：{exc.message}"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:300]}
    return {"ok": bool(data.get("ok")), "latency_ms": int(
        (time.perf_counter() - started) * 1000), "model": options["model"]}


@router.post("/asr/check")
def check_asr(request: Request):
    cfg = request.app.state.cfg
    conn = db.connect(cfg.db_path)
    try:
        options = settings_service.asr_settings(cfg, conn)
    finally:
        conn.close()
    if options["backend"] == "mock":
        return {"ok": True, "message": "当前为 mock 后端，无需加载模型"}
    models = model_status(Path(options["model_dir"]))
    missing = [m["label"] for m in models if not m["ready"]]
    return {"ok": not missing,
            "message": "模型文件齐全" if not missing
            else "缺少或不完整：" + "、".join(missing),
            "models": models, "gpu": gpu_info()}


@router.get("/hotwords")
def get_hotwords(request: Request):
    return {"items": _hotwords(request.app.state.cfg)}


@router.put("/hotwords")
def save_hotwords(request: Request, payload: dict = Body(...)):
    cfg = request.app.state.cfg
    words = payload.get("items")
    if words is None:
        words = str(payload.get("text", "")).splitlines()
    cleaned = []
    for word in words:
        value = str(word).strip()
        if not value:
            continue
        if len(value) > 64:
            raise ApiError(400, "invalid_hotword", f"热词过长：{value[:20]}")
        if value not in cleaned:
            cleaned.append(value)
    if len(cleaned) > 500:
        raise ApiError(400, "invalid_hotword", "热词最多 500 个")
    cfg.hotword_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = cfg.hotword_file.with_name(cfg.hotword_file.name + ".part")
    tmp.write_text("\n".join(cleaned) + ("\n" if cleaned else ""), encoding="utf-8")
    os.replace(str(tmp), str(cfg.hotword_file))
    return {"ok": True, "count": len(cleaned)}


@router.get("/templates")
def list_templates(request: Request):
    conn = db.connect(request.app.state.cfg.db_path)
    try:
        return {"items": settings_service.list_templates(conn),
                "sections": list(settings_service.SECTION_KEYS)}
    finally:
        conn.close()


@router.post("/templates")
def save_template(request: Request, payload: dict = Body(...)):
    conn = db.connect(request.app.state.cfg.db_path)
    try:
        saved = settings_service.save_template(conn, payload)
    except ValueError as exc:
        raise ApiError(400, "invalid_template", str(exc)) from exc
    finally:
        conn.close()
    return {"ok": True, "template": saved}


@router.delete("/templates/{key}")
def delete_template(key: str, request: Request):
    conn = db.connect(request.app.state.cfg.db_path)
    try:
        settings_service.delete_template(conn, key)
    except ValueError as exc:
        raise ApiError(400, "invalid_template", str(exc)) from exc
    finally:
        conn.close()
    return {"ok": True}


@router.post("/meetings/{uid}/close")
def close_meeting(uid: str, request: Request, payload: dict = Body(...)):
    try:
        return meeting_service.set_closed(
            request.app.state.cfg, uid, bool(payload.get("closed")))
    except LookupError as exc:
        raise ApiError(404, "not_found", str(exc)) from exc


@router.post("/meetings/{uid}/regenerate")
def regenerate(uid: str, request: Request):
    try:
        return meeting_service.regenerate_minutes(request.app.state.cfg, uid)
    except LookupError as exc:
        raise ApiError(404, "not_found", str(exc)) from exc
    except ValueError as exc:
        raise ApiError(409, "invalid_state", str(exc)) from exc


@router.delete("/meetings/{uid}")
def delete_meeting(uid: str, request: Request):
    ok, message = meeting_service.delete_meeting(request.app.state.cfg, uid)
    if not ok:
        raise ApiError(404, "not_found", message)
    return {"ok": True, "message": message}


@router.post("/rebuild-archives")
def rebuild_archives(request: Request):
    count = archive.rebuild_all(request.app.state.cfg)
    return {"ok": True, "count": count}


@router.get("/users")
def list_users(request: Request):
    conn = db.connect(request.app.state.cfg.db_path)
    try:
        items = user_service.list_users(conn)
    finally:
        conn.close()
    return {"items": items, "current": request.state.user["id"],
            "roles": sorted(user_service.ROLES)}


@router.post("/users")
def create_user(request: Request, payload: dict = Body(...)):
    conn = db.connect(request.app.state.cfg.db_path)
    try:
        user = user_service.create_user(conn, payload)
    except ValueError as exc:
        raise ApiError(400, "invalid_user", str(exc)) from exc
    finally:
        conn.close()
    return {"ok": True, "user": user}


@router.put("/users/{user_id}")
def update_user(user_id: int, request: Request, payload: dict = Body(...)):
    conn = db.connect(request.app.state.cfg.db_path)
    try:
        user = user_service.update_user(conn, user_id, payload)
    except LookupError as exc:
        raise ApiError(404, "not_found", str(exc)) from exc
    except ValueError as exc:
        raise ApiError(400, "invalid_user", str(exc)) from exc
    finally:
        conn.close()
    return {"ok": True, "user": user}


@router.delete("/users/{user_id}")
def delete_user(user_id: int, request: Request):
    conn = db.connect(request.app.state.cfg.db_path)
    try:
        user_service.delete_user(conn, user_id, request.state.user["id"])
    except LookupError as exc:
        raise ApiError(404, "not_found", str(exc)) from exc
    except ValueError as exc:
        raise ApiError(400, "invalid_user", str(exc)) from exc
    finally:
        conn.close()
    return {"ok": True}


@router.post("/password")
def change_password(request: Request, payload: dict = Body(...)):
    conn = db.connect(request.app.state.cfg.db_path)
    try:
        user_service.change_password(
            conn, request.state.user["id"],
            str(payload.get("old_password", "")),
            str(payload.get("new_password", "")))
    except LookupError as exc:
        raise ApiError(404, "not_found", str(exc)) from exc
    except ValueError as exc:
        raise ApiError(400, "invalid_password", str(exc)) from exc
    finally:
        conn.close()
    return {"ok": True, "relogin": True}
