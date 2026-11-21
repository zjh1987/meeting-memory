"""构建内网离线安装包。

在能上外网、且与目标服务器同系统同架构的准备机上执行：
    python deploy/offline/build_bundle.py            # Windows 准备机
    python3 deploy/offline/build_bundle.py --zip     # Linux 准备机

产物目录 dist/meeting-memory-offline-<平台>/ 可直接拷贝进内网，
在目标机执行 install.ps1（Windows）或 install.sh（Linux）。
"""

import argparse
import json
import platform
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache")
APP_ITEMS = [
    "app", "config", "deploy", "requirements.txt", "requirements-asr.txt",
    ".env.example",
]
TORCH_INDEX = "https://download.pytorch.org/whl/cu124"


def platform_tag() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system == "windows":
        return "windows-x64"
    if system == "linux":
        return "linux-x64" if machine in {"x86_64", "amd64"} else f"linux-{machine}"
    raise SystemExit(f"暂不支持当前系统：{system}")


def copy_item(src: Path, dst: Path) -> None:
    if src.is_dir():
        shutil.copytree(src, dst, ignore=IGNORE, dirs_exist_ok=True)
    else:
        shutil.copy2(src, dst)


def download_wheels(dest: Path, torch_index: str, seed: Path | None) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    if seed and seed.is_dir():
        for wheel in seed.glob("*.whl"):
            shutil.copy2(wheel, dest / wheel.name)
        print(f"已复用本地轮子：{seed}")
    cmd = [sys.executable, "-m", "pip", "download", "-d", str(dest),
           "-r", str(ROOT / "requirements.txt"),
           "-r", str(ROOT / "requirements-asr.txt")]
    if seed and seed.is_dir():
        cmd += ["--find-links", str(seed)]
    if torch_index:
        cmd += ["--extra-index-url", torch_index]
    print("下载依赖：" + " ".join(cmd))
    subprocess.run(cmd, check=True)


def find_ffmpeg_dir() -> Path | None:
    found = shutil.which("ffmpeg")
    if found:
        return Path(found).resolve().parent
    candidates = [Path(r"D:\FP\omarchy\tools\ffmpeg\bin")]
    for path in candidates:
        if (path / "ffmpeg.exe").exists() or (path / "ffmpeg").exists():
            return path
    return None


def dir_size(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def main() -> int:
    parser = argparse.ArgumentParser(description="构建内网离线安装包")
    parser.add_argument("--output", default=str(ROOT / "dist"))
    parser.add_argument("--skip-models", action="store_true",
                        help="不打包 models/funasr（目标机已有模型时使用）")
    parser.add_argument("--skip-wheels", action="store_true",
                        help="不下载 wheel（仅验证目录结构）")
    parser.add_argument("--torch-index-url", default=TORCH_INDEX,
                        help="PyTorch 轮子索引；纯 CPU 服务器可传空字符串")
    parser.add_argument("--seed-wheels", default="",
                        help="已有轮子目录（如 torch 大包），优先复用不重复下载")
    parser.add_argument("--zip", action="store_true", help="额外生成 zip")
    args = parser.parse_args()

    tag = platform_tag()
    bundle = Path(args.output).resolve() / f"meeting-memory-offline-{tag}"
    if bundle.exists():
        shutil.rmtree(bundle)
    bundle.mkdir(parents=True)
    print(f"构建目录：{bundle}")

    for name in APP_ITEMS:
        src = ROOT / name
        if not src.exists():
            raise SystemExit(f"缺少必需文件：{src}")
        copy_item(src, bundle / name)

    # 安装入口放在包根目录，便于拷入内网后直接执行。
    for name in ("install.sh", "install.ps1", "README.md"):
        shutil.copy2(ROOT / "deploy" / "offline" / name, bundle / name)
    # Windows PowerShell 5 无 BOM 时按本地代码页解析，中文脚本会报语法错。
    ps1 = bundle / "install.ps1"
    data = ps1.read_bytes()
    if not data.startswith(b"\xef\xbb\xbf"):
        ps1.write_bytes(b"\xef\xbb\xbf" + data)

    if not args.skip_wheels:
        seed = Path(args.seed_wheels).resolve() if args.seed_wheels else None
        download_wheels(bundle / "wheels", args.torch_index_url, seed)

    models = ROOT / "models" / "funasr"
    if not args.skip_models:
        if not models.is_dir():
            raise SystemExit(f"缺少模型目录：{models}")
        copy_item(models, bundle / "models" / "funasr")

    ffmpeg_dir = find_ffmpeg_dir()
    if ffmpeg_dir:
        target = bundle / "tools" / "ffmpeg" / "bin"
        target.mkdir(parents=True, exist_ok=True)
        for name in ("ffmpeg.exe", "ffmpeg", "ffprobe.exe", "ffprobe"):
            src = ffmpeg_dir / name
            if src.exists():
                shutil.copy2(src, target / name)
        print(f"已打包 FFmpeg：{ffmpeg_dir}")
    else:
        print("警告：未找到 FFmpeg，目标机需自行提供并加入 PATH")

    manifest = {
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "platform": tag,
        "python": platform.python_version(),
        "wheel_count": len(list((bundle / "wheels").glob("*")))
        if (bundle / "wheels").is_dir() else 0,
        "wheel_bytes": dir_size(bundle / "wheels")
        if (bundle / "wheels").is_dir() else 0,
        "models_bytes": dir_size(bundle / "models")
        if (bundle / "models").is_dir() else 0,
        "ffmpeg": bool(ffmpeg_dir),
        "torch_index_url": args.torch_index_url,
    }
    (bundle / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print("清单：" + json.dumps(manifest, ensure_ascii=False))

    if args.zip:
        archive = shutil.make_archive(str(bundle), "zip", root_dir=bundle)
        print(f"压缩包：{archive}")

    print("完成。将整个目录拷入内网后执行对应安装脚本。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
