"""任务执行器：领取 → 转写 → 纪要 → 关联 → 归档。"""

import json
import shutil
import threading
import time
import traceback
from datetime import datetime, timedelta

from app.config import Config
from app.core import state
from app.core.logging import log_event
from app.pipeline import archive, minutes as minutes_pipeline, relations, transcribe
from app.pipeline.minutes import MinutesValidationError
from app.providers.errors import ProviderError
from app.services import settings as settings_service
from app.storage import action_repo, db, meeting_repo, relation_repo
from app.web import context, render


def _finalize(cfg: Config, conn, meeting: dict) -> None:
    audio = cfg.ready_dir / meeting["audio_filename"]
    if audio.exists():
        shutil.move(str(audio), str(cfg.archive_dir / audio.name))
    fresh = meeting_repo.get_by_id(conn, meeting["id"])
    ctx = context.build_context(conn, fresh)
    html = render.render("meeting.html", m=fresh, standalone=True,
                         labels=state.STATUS_LABELS,
                         progress=state.progress_of(fresh["status"]), **ctx)
    archive.write_meeting(cfg, fresh, html)
    archive.refresh_indices(cfg)


def _minutes_failed(conn, meeting: dict, code: str, message: str) -> None:
    meeting_repo.set_status(conn, meeting["id"], "done", code, message[:500])


def _run_relations(cfg, conn, meeting):
    try:
        meeting_repo.set_status(conn, meeting["id"], "relating")
        fresh = meeting_repo.get_by_id(conn, meeting["id"])
        data = json.loads(fresh["minutes"])
        relation_repo.replace(conn, meeting["id"],
                              relations.build_relations(conn, fresh, data))
        meeting_repo.set_status(conn, meeting["id"], "done")
    except Exception as exc:
        traceback.print_exc()
        log_event("error", "relation_failed", uid=meeting["uid"],
                  detail=str(exc))
        meeting_repo.set_status(conn, meeting["id"], "done",
                                "relation_failed", str(exc)[:500])


def _process(cfg: Config, conn, meeting: dict) -> None:
    stage = state.resume_stage(meeting["transcript"], meeting["minutes"])
    log_event("info", "stage", uid=meeting["uid"], stage=stage)
    segments = json.loads(meeting["transcript"]) if meeting["transcript"] else None
    llm_options = settings_service.llm_settings(cfg, conn)
    asr_options = settings_service.asr_settings(cfg, conn)
    template = settings_service.get_template(conn, meeting["template_key"])

    if stage == "transcribe":
        started = time.perf_counter()
        segments = transcribe.run(cfg, meeting, asr_options,
                                  asr_options["max_duration_min"])
        asr_seconds = round(time.perf_counter() - started, 2)
        audio_seconds = float(segments[-1]["end"]) if segments else 0.0
        meeting_repo.update_fields(
            conn, meeting["id"],
            transcript=json.dumps(segments, ensure_ascii=False),
            duration_sec=int(audio_seconds),
            asr_seconds=asr_seconds,
            audio_seconds=audio_seconds,
        )
        meeting_repo.set_status(conn, meeting["id"], "minuting")
    elif stage == "minutes":
        meeting_repo.set_status(conn, meeting["id"], "minuting")

    if stage in {"transcribe", "minutes"}:
        try:
            glossary = []
            try:
                glossary = [w.strip() for w in cfg.hotword_file.read_text(
                    encoding="utf-8").splitlines() if w.strip()][:50]
            except OSError:
                pass
            data = minutes_pipeline.generate(
                cfg, segments or [], meeting["template_key"],
                llm_settings=llm_options, hint=template["hint"],
                custom_sections=template.get("custom_sections") or [],
                glossary=glossary)
        except MinutesValidationError as exc:
            _minutes_failed(conn, meeting, "llm_bad_json", str(exc))
            _finalize(cfg, conn, meeting)
            return
        except ProviderError as exc:
            if exc.transient:
                raise
            _minutes_failed(conn, meeting, exc.code, exc.message)
            _finalize(cfg, conn, meeting)
            return
        action_repo.replace(conn, meeting["id"], data.get("actions", []))
        meeting_repo.update_fields(
            conn, meeting["id"],
            minutes=json.dumps(data, ensure_ascii=False),
            error_code=None, error_msg=None,
        )

    _run_relations(cfg, conn, meeting)
    _finalize(cfg, conn, meeting)


def _heartbeat(cfg: Config, meeting_id: int, stop: threading.Event) -> None:
    while not stop.wait(cfg.heartbeat_interval):
        try:
            conn = db.connect(cfg.db_path)
            try:
                meeting_repo.touch(conn, meeting_id)
            finally:
                conn.close()
        except Exception:
            traceback.print_exc()


def _retry_or_fail(cfg: Config, conn, meeting: dict, exc: ProviderError) -> None:
    if exc.transient and meeting["retry_count"] < cfg.auto_retry_max:
        log_event("warn", "retry", uid=meeting["uid"], code=exc.code)
        next_at = (datetime.now() + timedelta(seconds=cfg.retry_backoff_sec))
        meeting_repo.update_fields(
            conn, meeting["id"], status="pending",
            retry_count=meeting["retry_count"] + 1,
            next_retry_at=next_at.strftime("%Y-%m-%d %H:%M:%S"),
            error_code=exc.code, error_msg=exc.message,
            started_at=None, heartbeat_at=None,
        )
    else:
        log_event("error", "failed", uid=meeting["uid"], code=exc.code)
        meeting_repo.set_status(conn, meeting["id"], "failed",
                                exc.code, exc.message[:500])


def process_once(cfg: Config) -> bool:
    conn = db.connect(cfg.db_path)
    try:
        meeting = meeting_repo.claim_next(conn)
        if not meeting:
            return False
        stop = threading.Event()
        heartbeat = threading.Thread(target=_heartbeat,
                                     args=(cfg, meeting["id"], stop), daemon=True)
        heartbeat.start()
        try:
            _process(cfg, conn, meeting)
        except ProviderError as exc:
            _retry_or_fail(cfg, conn, meeting, exc)
        except Exception:
            traceback.print_exc()
            log_event("error", "exception", uid=meeting["uid"],
                      detail=traceback.format_exc())
            meeting_repo.set_status(conn, meeting["id"], "failed",
                                    "internal", "处理异常，详见日志")
        finally:
            stop.set()
            heartbeat.join(timeout=1)
        return True
    finally:
        conn.close()


def start(cfg: Config, stop: threading.Event) -> threading.Thread:
    def loop() -> None:
        while not stop.is_set():
            try:
                if not process_once(cfg):
                    stop.wait(1.0)
            except Exception:
                traceback.print_exc()
                stop.wait(1.0)

    thread = threading.Thread(target=loop, daemon=True, name="worker")
    thread.start()
    return thread
