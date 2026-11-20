import sys
import types
from dataclasses import replace

from app.providers.asr_funasr import FunAsrProvider


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
