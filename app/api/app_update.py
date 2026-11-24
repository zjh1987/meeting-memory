"""Android 应用内升级：发布信息查询与安装包下载（无需登录）。"""

import hashlib
import json
import os
import re
from pathlib import Path

from fastapi import APIRouter, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from app.config import Config

router = APIRouter()

MANIFEST_NAME = "latest.json"
VERSION_NAME = re.compile(r"^[0-9A-Za-z._-]{1,32}$")


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def latest_release(cfg: Config) -> dict | None:
    manifest = cfg.app_dir / MANIFEST_NAME
    if not manifest.is_file():
        return None
    try:
        meta = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    filename = str(meta.get("file") or "")
    apk = cfg.app_dir / filename
    if not filename or Path(filename).name != filename \
            or apk.suffix.lower() != ".apk" or not apk.is_file():
        return None
    return {
        "version_code": int(meta.get("version_code") or 0),
        "version_name": str(meta.get("version_name") or ""),
        "notes": str(meta.get("notes") or ""),
        "size": apk.stat().st_size,
        "sha256": str(meta.get("sha256") or sha256_of(apk)),
        "url": f"/downloads/{filename}",
    }


async def save_release(cfg: Config, upload: UploadFile, version_code: int,
                       version_name: str, notes: str) -> dict:
    if version_code <= 0:
        raise ValueError("版本号必须是正整数")
    name = (version_name or str(version_code)).strip()
    if not VERSION_NAME.fullmatch(name):
        raise ValueError("版本名称只能使用字母、数字、点、下划线和减号")
    filename = f"meeting-memory-android-{name}.apk"
    target = cfg.app_dir / filename
    tmp = target.with_name(filename + ".part")
    try:
        with tmp.open("wb") as handle:
            while True:
                chunk = await upload.read(1024 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
        if tmp.stat().st_size == 0:
            raise ValueError("安装包为空")
        os.replace(str(tmp), str(target))
    finally:
        tmp.unlink(missing_ok=True)
    meta = {
        "version_code": version_code,
        "version_name": name,
        "notes": (notes or "").strip(),
        "file": filename,
        "sha256": sha256_of(target),
    }
    manifest = cfg.app_dir / MANIFEST_NAME
    part = manifest.with_name(MANIFEST_NAME + ".part")
    part.write_text(json.dumps(meta, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    os.replace(str(part), str(manifest))
    return {**meta, "size": target.stat().st_size,
            "url": f"/downloads/{filename}"}


@router.get("/api/app/android/latest")
def latest_android(request: Request):
    info = latest_release(request.app.state.cfg)
    if info is None:
        return {"available": False}
    return {"available": True, **info}


@router.get("/downloads/{filename}")
def download_android(filename: str, request: Request):
    cfg = request.app.state.cfg
    if Path(filename).name != filename or not filename.lower().endswith(".apk"):
        return JSONResponse(
            {"error": {"code": "not_found", "message": "文件不存在"}},
            status_code=404)
    path = cfg.app_dir / filename
    if not path.is_file():
        return JSONResponse(
            {"error": {"code": "not_found", "message": "文件不存在"}},
            status_code=404)
    return FileResponse(path, media_type="application/vnd.android.package-archive",
                        filename=filename)
