import sys
import types
from dataclasses import replace

import pytest

from app.providers import asr_funasr
from app.providers.asr_funasr import FunAsrProvider


@pytest.fixture(autouse=True)
def _clear_model_cache():
    asr_funasr._reset_cache_for_tests()
    yield
    asr_funasr._reset_cache_for_tests()


def _prepare_dirs(cfg):
    for name in ("asr", "vad", "punc", "spk"):
        (cfg.funasr_model_dir / name).mkdir(parents=True, exist_ok=True)


def test_parses_sentence_info_and_speakers(cfg, monkeypatch, tmp_path):
    _prepare_dirs(cfg)
    calls = {}

    class FakeModel:
        def generate(self, **kwargs):
            calls.update(kwargs)
            return [{"sentence_info": [
                {"start": 0, "end": 1500, "spk": 0, "text": "第一句。"},
                {"start": 1500, "end": 3200, "spk": 1, "text": "第二句。"},
            ]}]

    fake_module = types.ModuleType("funasr")
    fake_module.AutoModel = lambda **kwargs: FakeModel()
    monkeypatch.setitem(sys.modules, "funasr", fake_module)

    provider = FunAsrProvider(replace(cfg, asr_backend="funasr"))
    segments = provider.transcribe(tmp_path / "a.wav")

    assert [s["speaker"] for s in segments] == ["说话人1", "说话人2"]
    assert segments[1]["start"] == 1.5
    assert segments[1]["end"] == 3.2
    assert calls["input"].endswith("a.wav")


def test_model_is_cached_across_providers(cfg, monkeypatch, tmp_path):
    _prepare_dirs(cfg)
    built = []

    class FakeModel:
        def generate(self, **kwargs):
            return [{"sentence_info": [
                {"start": 0, "end": 1000, "spk": 0, "text": "你好。"},
            ]}]

    def fake_auto_model(**kwargs):
        built.append(kwargs)
        return FakeModel()

    fake_module = types.ModuleType("funasr")
    fake_module.AutoModel = fake_auto_model
    monkeypatch.setitem(sys.modules, "funasr", fake_module)

    tuned = replace(cfg, asr_backend="funasr")
    first = FunAsrProvider(tuned)
    second = FunAsrProvider(tuned)
    assert first.transcribe(tmp_path / "a.wav")[0]["text"] == "你好。"
    assert second.transcribe(tmp_path / "b.wav")[0]["text"] == "你好。"
    assert first._model is second._model
    assert len(built) == 1
