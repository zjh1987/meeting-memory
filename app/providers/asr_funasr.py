"""本地 FunASR：paraformer-zh + fsmn-vad + ct-punc + cam++。

模型目录约定：
    {FUNASR_MODEL_DIR}/asr    paraformer-zh
    {FUNASR_MODEL_DIR}/vad    fsmn-vad
    {FUNASR_MODEL_DIR}/punc   ct-punc
    {FUNASR_MODEL_DIR}/spk    cam++
"""

from pathlib import Path

from app.config import Config
from app.providers.errors import ProviderError

# 模型加载很重，按 (模型目录, 设备, 聚类阈值) 复用，避免每场会议重复加载。
_MODELS: dict[tuple[str, str, float], object] = {}


def _reset_cache_for_tests() -> None:
    _MODELS.clear()


class FunAsrProvider:
    def __init__(self, cfg: Config):
        self.model_dir = cfg.funasr_model_dir
        self.device = cfg.funasr_device
        self.hotword_file = cfg.hotword_file
        self.speaker_threshold = cfg.speaker_threshold
        self._model = None

    def _load(self):
        if self._model is not None:
            return self._model
        dirs = {name: self.model_dir / name
                for name in ("asr", "vad", "punc", "spk")}
        for label, path in dirs.items():
            if not path.exists():
                raise ProviderError("asr_unavailable", f"模型目录缺失：{path}")
        key = (str(self.model_dir), self.device, self.speaker_threshold)
        model = _MODELS.get(key)
        if model is None:
            try:
                from funasr import AutoModel
            except ImportError as exc:
                raise ProviderError(
                    "asr_unavailable",
                    "未安装 funasr，请执行 python -m pip install -r requirements-asr.txt",
                ) from exc
            model = AutoModel(
                model=str(dirs["asr"]),
                vad_model=str(dirs["vad"]),
                punc_model=str(dirs["punc"]),
                spk_model=str(dirs["spk"]),
                spk_kwargs={"cb_kwargs": {"merge_thr": self.speaker_threshold}},
                device=self.device,
                disable_update=True,
            )
            _MODELS[key] = model
        self._model = model
        return model

    def _hotwords(self) -> str | None:
        if not self.hotword_file.exists():
            return None
        words = [w.strip() for w in
                 self.hotword_file.read_text(encoding="utf-8").splitlines()
                 if w.strip()]
        return " ".join(words) or None

    def transcribe(self, audio_path: Path) -> list[dict]:
        model = self._load()
        try:
            result = model.generate(
                input=str(audio_path),
                hotword=self._hotwords(),
                sentence_timestamp=True,
            )
        except Exception as exc:
            raise ProviderError("asr_unavailable",
                                f"FunASR 识别失败：{exc}", transient=True) from exc
        if not result:
            return []

        item = result[0]
        segments: list[dict] = []
        for sentence in item.get("sentence_info") or []:
            text = (sentence.get("text") or "").strip()
            if not text:
                continue
            speaker = int(sentence.get("spk", 0)) + 1
            segments.append({
                "idx": len(segments),
                "start": round(float(sentence.get("start", 0)) / 1000.0, 2),
                "end": round(float(sentence.get("end", 0)) / 1000.0, 2),
                "speaker": f"说话人{speaker}",
                "text": text,
            })
        if not segments:
            text = (item.get("text") or "").strip()
            if text:
                segments.append({"idx": 0, "start": 0.0, "end": 0.0,
                                 "speaker": "说话人1", "text": text})
        return segments
