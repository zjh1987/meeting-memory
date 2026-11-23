from app.providers.asr_funasr import _friendly_error
from app.web.context import failure_hint


def test_failure_hint_for_asr_dtype_bug():
    meeting = {
        "error_code": "asr_unavailable",
        "error_msg": "FunASR 识别失败：Cannot interpret 'torch.float32' as a data type",
    }
    hint = failure_hint(meeting)
    assert "说话人分离" in hint
    assert "重试" in hint


def test_failure_hint_for_audio_too_long():
    hint = failure_hint({"error_code": "audio_too_long", "error_msg": ""})
    assert "上限" in hint


def test_friendly_error_maps_gpu_memory():
    message = _friendly_error(RuntimeError("CUDA out of memory. Tried to allocate"))
    assert "显存" in message


def test_friendly_error_keeps_unknown_detail():
    message = _friendly_error(RuntimeError("some unexpected failure"))
    assert "some unexpected failure" in message
