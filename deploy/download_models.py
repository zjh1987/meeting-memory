"""下载 FunASR 运行所需模型到本地模型目录。

用法：
    python deploy/download_models.py
    python deploy/download_models.py --output /vol1/meeting-memory/models/funasr

默认目录为 ./models/funasr，会被 docker-compose 挂载进容器。
纯离线环境请在有外网的机器上下载后，把整个目录拷入目标机。
"""

import argparse
from pathlib import Path

MODELS = {
    "asr": "iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch",
    "vad": "iic/speech_fsmn_vad_zh-cn-16k-common-pytorch",
    "punc": "iic/punc_ct-transformer_zh-cn-common-vocab272727-pytorch",
    "spk": "iic/speech_campplus_sv_zh-cn_16k-common",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="下载 FunASR 模型")
    parser.add_argument("--output", default="models/funasr",
                        help="模型根目录，默认 models/funasr")
    args = parser.parse_args()

    try:
        from modelscope import snapshot_download
    except ImportError:
        print("缺少 modelscope，请先执行：pip install -r requirements.txt")
        return 1

    root = Path(args.output).resolve()
    for name, model_id in MODELS.items():
        target = root / name
        target.mkdir(parents=True, exist_ok=True)
        print(f"下载 {model_id} -> {target}")
        snapshot_download(model_id, local_dir=str(target))
    print(f"完成：{root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
