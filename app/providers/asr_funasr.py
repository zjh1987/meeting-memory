"""本地 FunASR：paraformer-zh + fsmn-vad + ct-punc + cam++。

模型目录约定：
    {FUNASR_MODEL_DIR}/asr    paraformer-zh
    {FUNASR_MODEL_DIR}/vad    fsmn-vad
    {FUNASR_MODEL_DIR}/punc   ct-punc
    {FUNASR_MODEL_DIR}/spk    cam++
"""

from pathlib import Path
import traceback

from app.config import Config
from app.providers.errors import ProviderError

# 模型加载很重，按 (模型目录, 设备, 聚类阈值) 复用，避免每场会议重复加载。
_MODELS: dict[tuple[str, str, float], object] = {}
_CLUSTER_PATCHED = False


def _patch_cluster_backend() -> None:
    """FunASR 长音频说话人聚类的兼容补丁。

    超过 2048 个 VAD 片段时，FunASR 会走 UMAP/HDBSCAN 分支，并把 CUDA
    tensor 直接交给 NumPy/UMAP，触发
    ``Cannot interpret 'torch.float32' as a data type``。
    这里在进入聚类前统一转成 CPU NumPy，不改动 site-packages。
    """
    global _CLUSTER_PATCHED
    if _CLUSTER_PATCHED:
        return
    try:
        from funasr.models.campplus import cluster_backend
        import numpy as np
    except Exception:
        return

    original = cluster_backend.ClusterBackend.forward
    if getattr(original, "_meeting_memory_numpy", False):
        _CLUSTER_PATCHED = True
        return

    def forward(self, X, **params):
        if hasattr(X, "detach") and hasattr(X, "cpu"):
            X = X.detach().cpu().numpy()
        try:
            return original(self, X, **params)
        except Exception:
            # 聚类失败不应让整场转写失败；降级为单一说话人，保留逐字稿。
            traceback.print_exc()
            return np.zeros(len(X), dtype=int)

    forward._meeting_memory_numpy = True
    cluster_backend.ClusterBackend.forward = forward
    _CLUSTER_PATCHED = True


def _friendly_error(exc: Exception) -> str:
    text = str(exc)
    lower = text.lower()
    if "torch.float32" in text or "can't convert cuda" in lower:
        return ("长录音的说话人分离阶段失败：FunASR 与当前 NumPy/Torch "
                "版本不兼容。录音已保留，服务端升级后可直接重试。")
    if "out of memory" in lower or "显存" in text:
        return "GPU 显存不足。建议缩短单场录音，或升级显卡后重试。"
    if "no module named" in lower or "not found" in lower:
        return "ASR 模型或依赖缺失，请检查模型目录与服务端日志。"
    return f"FunASR 识别失败：{text}"


def _reset_cache_for_tests() -> None:
    global _CLUSTER_PATCHED
    _MODELS.clear()
    _CLUSTER_PATCHED = False


class FunAsrProvider:
    def __init__(self, cfg: Config, settings: dict | None = None):
        options = settings or {}
        self.model_dir = Path(options.get("model_dir", cfg.funasr_model_dir))
        self.device = options.get("device", cfg.funasr_device)
        self.hotword_file = cfg.hotword_file
        self.speaker_threshold = float(
            options.get("speaker_threshold", cfg.speaker_threshold))
        self._model = None

    def _load(self):
        if self._model is not None:
            return self._model
        _patch_cluster_backend()
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
            traceback.print_exc()
            raise ProviderError("asr_unavailable",
                                _friendly_error(exc), transient=True) from exc
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
