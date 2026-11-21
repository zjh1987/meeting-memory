# 内网离线安装包

在**能上外网、且与目标服务器同系统同架构**的准备机上构建，产物整目录拷入内网安装。
主目标为 Linux + systemd + Nginx；Windows 包仅用于本机演示。

## 构建

准备机需要：Python 3.10、pip、可访问 PyPI（GPU 版还需访问 PyTorch 轮子源）。

```bash
# Linux 准备机（对应内网 Linux 服务器）
python3 deploy/offline/build_bundle.py --zip

# Windows 演示包
python deploy/offline/build_bundle.py --zip

# 纯 CPU 服务器：不下载 CUDA 版 torch
python3 deploy/offline/build_bundle.py --torch-index-url "" --zip

# 目标机已有模型时可缩小包体
python3 deploy/offline/build_bundle.py --skip-models --zip
```

产物：`dist/meeting-memory-offline-<平台>/`（含 `manifest.json`），`--zip` 时附带同名压缩包。
包内含：应用代码、`wheels/`（全部依赖轮子）、`models/funasr/`（未跳过时）、`tools/ffmpeg/`（本机能找到时）。
应用依赖已锁定：funasr 1.4.27 / torch 2.5.1 / torchaudio 2.5.1 / modelscope 1.40.3 / transformers 4.46.3。

## 安装

目标机需预装：Python 3.10 + venv（Linux 还需 `python3-venv`）。离线包不包含解释器。

```bash
# Linux
sudo APP_DIR=/opt/meeting-memory ./install.sh

# Windows
$env:APP_DIR="D:\meeting-memory"; .\install.ps1
```

脚本会创建 `.venv`、离线安装全部依赖、复制模型与 FFmpeg，并从 `.env.example` 生成 `.env`。

## 安装后

1. 编辑 `.env`：`APP_PASSWORD`、`COOKIE_SECRET`、`ASR_BACKEND=funasr`、`FUNASR_DEVICE`、
   `LLM_BASE_URL`/`LLM_API_KEY`/`LLM_MODEL`。
2. Linux 服务：
   ```bash
   sudo cp deploy/systemd/mm.service /etc/systemd/system/
   sudo systemctl daemon-reload && sudo systemctl enable --now mm
   sudo cp deploy/nginx/mm.conf /etc/nginx/conf.d/ && sudo nginx -t && sudo systemctl reload nginx
   ```
3. 校验：`curl http://127.0.0.1:8000/healthz` 返回 `{"ok":true}`，再上传一段音频走完整链路。
4. 备份：`deploy/backup.sh` 可加入 cron；删除单场会议用 `deploy/delete_meeting.py <uid>`。

## 注意

- GPU 服务器需预装 NVIDIA 驱动；CUDA 运行库随 torch 轮子携带，无需单独装 CUDA Toolkit。
- 离线包体积主要来自 torch（约 2.5GB）与 FunASR 模型（约 1.2GB）。
- 包内 FFmpeg 取自构建机，跨发行版可能缺共享库；建议在目标机放置静态版并加入 `PATH`。
- 少数纯 Python 依赖以源码包分发（jieba、crcmod、antlr4），Linux 目标机需具备 `gcc`（`build-essential`）。
- 升级时重跑安装脚本即可，`.env`、`data/`、`site/`、`logs/` 不会被覆盖。
