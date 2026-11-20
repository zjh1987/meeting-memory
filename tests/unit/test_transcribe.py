from app.pipeline import transcribe
from app.providers import build_asr
from app.providers.errors import ProviderError


def test_mock_asr_segments_are_continuous(cfg):
    provider = build_asr(cfg)
    segments = provider.transcribe(cfg.inbox_dir / "whatever.m4a")
    assert segments
    assert [s["idx"] for s in segments] == list(range(len(segments)))
    assert all(s["speaker"] for s in segments)


def test_transcribe_stage_writes_file_check(cfg, tmp_path):
    audio = cfg.ready_dir / "u1__会.m4a"
    audio.write_bytes(b"x")
    meeting = {"id": 1, "uid": "u1", "audio_filename": audio.name,
               "template_key": "standard"}
    segments = transcribe.run(cfg, meeting)
    assert len(segments) > 3
    assert segments[0]["start"] == 0.0


def test_transcribe_missing_file_raises(cfg):
    meeting = {"id": 1, "uid": "u1", "audio_filename": "missing.m4a",
               "template_key": "standard"}
    try:
        transcribe.run(cfg, meeting)
        assert False, "应当抛出 ProviderError"
    except ProviderError as exc:
        assert exc.code == "file_missing"
