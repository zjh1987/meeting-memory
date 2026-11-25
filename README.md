# 会议记忆 · Meeting Memory

内网私有化部署的会议记忆系统：把会议录音交给它，自动完成 **转写 → 分人 → 结构化纪要 → 跨会议关联 → 静态归档**。所有音频、转写与纪要都留在自己的服务器上。

[![CI](https://github.com/zjh1987/meeting-memory/actions/workflows/ci.yml/badge.svg)](https://github.com/zjh1987/meeting-memory/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10-blue.svg)](https://www.python.org/)

## 功能

- **两种录入方式**：网页拖拽上传，或把文件写入 `data/inbox/` 由后台自动采集（支持 `.part` 完成后改名）。
- **本地语音识别**：FunASR `paraformer-zh` + `fsmn-vad` + `ct-punc` + `cam++`，中文转写、标点恢复与说话人分离，可跑在 CPU 或 NVIDIA GPU 上。
- **结构化纪要**：通过 OpenAI 兼容接口调用大模型，内置常规会议、座谈交流、工作汇报、周会、项目复盘、决策评审、客户访谈等模板，支持自定义展示模块。
- **自动命名**：未填写会议名称时，根据纪要标题或摘要首句自动生成 20 字以内的会议名；手动重命名后不再自动覆盖。
- **跨会议记忆**：自动识别「上次待办未落实」与「议题重复出现」，每条关联都带原文引用，不做开放式联想。支持按时间范围回看、用同义词提示词补充匹配，并在后台调节阈值；全部为本地规则计算，不额外调用大模型。
- **项目管理**：管理员可在后台新建、重命名、归集和删除项目，也可逐场调整会议归属，上传页与手机 App 的下拉选项立即同步。
- **数据隔离**：普通成员只能看到归属自己的会议、纪要与项目；管理员仍可查看和管理全部内容，并可在会议管理中调整归属账号；静态归档也仅管理员可访问。
- **进度可视**：`接收 → 转写 → 纪要 → 关联 → 归档` 全程状态与百分比，失败原因可见、支持手动重试与自动重试一次。
- **静态归档**：按日期生成可直接双击打开的 HTML，含当日索引页，适合长期留存。
- **账号与权限**：管理员 / 成员两种角色，PBKDF2 密码哈希，登录限流，管理员可在后台管理账号与运行时设置。
- **可离线演示**：ASR 与 LLM 同时使用 mock 提供者时，无需任何外部服务即可跑通全链路。

## 工作流

```text
音频文件 ──► data/inbox/ 或网页上传
              │
              ▼
        ┌─────────────┐    ┌──────────────┐    ┌──────────────┐
        │  Harvester  │───►│    Worker    │───►│  Maintainer  │
        │ 采集/落盘    │    │ 转写→纪要→关联│    │ 归档/清理     │
        └─────────────┘    └──────────────┘    └──────────────┘
              │                   │                   │
              ▼                   ▼                   ▼
          SQLite（任务队列）   结构化纪要         site/YYYY/MM/DD/
```

单进程 FastAPI + SQLite（WAL）+ 三个后台线程；会议表本身充当任务队列，用状态机条件更新避免重复处理。

## Android 客户端

手机端录音终端位于 [`android/`](android/)，支持：

- 前台服务长录音：暂停/继续、锁屏继续、来电自动暂停、到达时长自动保存
- 停止后自动上传；WorkManager 断网重试、仅 Wi-Fi 上传、失败队列
- 16 kHz WAV 直接落盘，进程被系统回收后可修复文件头并恢复录音
- 本机录音播放、重命名、分享、删除，以及服务器转写/纪要状态跟踪
- 内嵌完整 Web 管理界面：概览、会议、上传、后台与静态归档
- 会话 Cookie 加密保存；支持内网自签 HTTPS 证书
- 通知栏控制录音，纪要生成完成与上传失败都会提醒

安装包位于 `dist/会议记忆-Android-v1.0.3.apk`（二进制不入库），支持 Android 8.0 及以上。首次打开填写服务器地址（如 `http://192.168.110.14:8000`）和账号即可。

**应用内升级**：管理员在后台“App 更新”上传新 APK 后，手机启动时会自动检测并提示升级（每 12 小时最多检查一次），也可在“我的 → 检查更新”手动触发。下载完成后覆盖安装，无需卸载；Web 管理界面本身随服务器更新即时生效。首次升级需按系统提示允许本应用安装未知来源应用。

首页“本机录音”右侧的“导入”可以直接选择手机“录音”“下载”等目录里的音频；Web 上传页的系统文件选择器也已改为可浏览全部文件。管理后台支持 CSV 批量导入账号、调整纪要模板顺序、管理项目与会议归属、配置跨会议关联，普通成员无法重新生成纪要、结案或重试处理。

自行构建需要 JDK 17 与 Android SDK 34：

```bash
cd android
./gradlew assembleRelease     # 需要 keystore.properties；否则可用 assembleDebug
```

签名配置放在 `android/keystore.properties`（已加入 `.gitignore`）。录音约 115 MB/小时，默认单场最长 360 分钟、仅 Wi-Fi 上传，可在 App“我的”中调整；服务器侧上限由 `MAX_UPLOAD_MB` 控制。

### 长录音与转写失败

超长会议（超过 2048 个语音片段）会走 FunASR 的 UMAP 说话人聚类分支。服务端已加入 CUDA/NumPy 兼容修复，并在聚类异常时降级为单一说话人，保证逐字稿和纪要仍能生成。会议详情页在失败时会显示可读原因和“技术详情”，原始音频保留在服务器，可直接点“重试处理”；如果提示超过时长上限，请缩短录音或调大 `MAX_DURATION_MIN`。

## 技术栈

Python 3.10 · FastAPI · Jinja2 · SQLite · FunASR · PyTorch · FFmpeg · Docker

## 快速开始

### 方式一：Docker（推荐）

需要 Docker 与 Docker Compose。首次启动前先准备配置和模型：

```bash
git clone https://github.com/zjh1987/meeting-memory.git
cd meeting-memory

cp .env.example .env
# 编辑 .env，至少设置 APP_PASSWORD；真实转写需设置 ASR_BACKEND=funasr

# 下载 FunASR 模型到 ./models/funasr（约 1.2 GB）
# 宿主机没有 Python 时，可在任意能上网的机器下载后把整个 models/funasr 拷过来
pip install modelscope
python deploy/download_models.py

docker compose up -d --build
```

打开 `http://<服务器IP>:8000`，使用 `admin` 与 `.env` 中的 `APP_PASSWORD` 登录。

NVIDIA GPU 主机在确认 `nvidia-smi` 可用且存在 `/dev/nvidia*` 后，改用 GPU 覆盖配置：

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build
```

> 容器 GPU 直通依赖宿主导出的用户态库目录 `./nvidia-libs`。NAS 等无官方 runtime 的环境可参考 [deploy/nas](deploy/nas) 下的脚本；若只想快速体验，可先把 `.env` 中的 `FUNASR_DEVICE` 设为 `cpu`。

### 方式二：本地运行

需要 Python 3.10 与 FFmpeg（真实转写时需要）。

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env    # Windows: copy .env.example .env
# 编辑 .env

python -m uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000
```

### 只想先看看效果

在 `.env` 中保持：

```dotenv
ASR_BACKEND=mock
LLM_PROVIDER=mock
```

即可不上传模型、不配置大模型，直接上传音频走完整流程（转写与纪要为示例内容）。

## 配置

全部配置来自环境变量或 `.env`。完整示例见 [.env.example](.env.example)。

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `APP_PASSWORD` | 空（必填） | 首次启动时创建 `admin` 账号使用的初始密码 |
| `COOKIE_SECRET` | 由口令派生 | 登录 Cookie 签名密钥，生产建议显式设置随机值 |
| `DATA_DIR` | `./data` | 数据目录，含 `inbox/`、`ready/`、`archive/` |
| `SITE_DIR` | `./site` | 静态归档输出目录 |
| `ASR_BACKEND` | `mock` | `mock` 或 `funasr` |
| `FUNASR_MODEL_DIR` | `./models/funasr` | 模型根目录，需包含 `asr/`、`vad/`、`punc/`、`spk/` |
| `FUNASR_DEVICE` | `cpu` | `cpu` 或 `cuda:0` |
| `HOTWORD_FILE` | `./config/hotwords.txt` | 热词表，每行一个词 |
| `LLM_PROVIDER` | `mock` | `mock` 或 `openai`（任意 OpenAI 兼容接口） |
| `LLM_BASE_URL` | 空 | 例如 `https://api.deepseek.com/v1` |
| `LLM_API_KEY` | 空 | 大模型 API Key |
| `LLM_MODEL` | 空 | 例如 `deepseek-chat` |
| `MAX_UPLOAD_MB` | `1024` | 单文件上传上限 |
| `MIN_FREE_GB` | `5` | 磁盘剩余空间低于该值时暂停接收新任务 |
| `SPEAKER_THRESHOLD` | `0.75` | 说话人聚类阈值，越高越容易拆分 |
| `MAX_DURATION_MIN` | `360` | 单场录音最长时长（分钟），`0` 表示不限制 |
| `SCAN_INTERVAL` | `3` | 采集目录扫描间隔（秒） |
| `HEARTBEAT_INTERVAL` | `60` | 任务心跳间隔（秒） |
| `ZOMBIE_TIMEOUT` | `180` | 超时未心跳视为僵尸任务的秒数 |
| `AUTO_RETRY_MAX` | `1` | 自动重试次数 |
| `RETRY_BACKOFF_SEC` | `30` | 重试退避秒数 |
| `LOG_DIR` | `./logs` | 日志目录 |

部分参数（ASR 后端、设备、阈值、LLM 配置等）也可以在登录后由管理员在 `/admin` 页面修改，数据库中的运行时设置优先于 `.env`。

## 账号

- 首次启动时自动创建管理员 `admin`，密码为 `APP_PASSWORD`。
- 管理员可在 `/admin` 新增成员、调整角色、重置密码。
- 忘记密码时在服务器上执行：

```bash
python deploy/reset_password.py admin
# 或
python deploy/reset_password.py admin --password '新密码'
```

重置后该账号所有登录会话立即失效。

## 部署

### 目录约定

```text
data/inbox/     待处理音频（外部设备可写入）
data/ready/     已转码待处理
data/archive/   原始音频归档
data/app.db     SQLite 数据库
site/           静态归档 HTML
logs/           运行日志
models/funasr/  ASR 模型
config/         热词与配置
deploy/         部署脚本（systemd / Nginx / NAS / 离线包）
```

### Linux systemd + Nginx

```bash
sudo cp deploy/systemd/mm.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now mm

sudo cp deploy/nginx/mm.conf /etc/nginx/conf.d/
sudo nginx -t && sudo systemctl reload nginx
```

`mm.service` 默认使用 `/opt/meeting-memory` 与 `mm` 用户，按实际路径和用户修改。Nginx 示例同时限制 `/site/` 仅内网访问。

### NAS / NVIDIA GPU

`deploy/nas/` 提供了在 Debian 系 NAS 上启用 NVIDIA 显卡的经验脚本：

- `install_nvidia_userspace.sh`：仅安装与内核模块版本一致的用户态驱动，不动内核模块、DRM 与 OpenGL。
- `make_nvidia_libs.sh`：导出容器所需的 `libcuda` / `libnvidia*` 到 `nvidia-libs/`。
- `install_boot_unit.sh`：开机创建 `/dev/nvidia*` 设备节点，避免重启后容器起不来。
- `run_build.sh`：后台构建镜像并写日志。

脚本中的 `/vol1/meeting-memory` 等路径需按你的环境修改。不同 NAS 发行版的驱动来源差异较大，执行前请确认内核模块版本与驱动版本严格一致。

### 内网离线安装包

在能上网的准备机上构建包含全部 Python 轮子与模型的离线包：

```bash
python deploy/offline/build_bundle.py --zip
```

产物在 `dist/meeting-memory-offline-<平台>/`，拷入内网后执行 `install.ps1`（Windows）或 `install.sh`（Linux）。详见 [deploy/offline/README.md](deploy/offline/README.md)。

## 开发与测试

测试使用 mock 提供者，不需要 GPU、模型或大模型接口：

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```

代码结构：

```text
app/
  api/          HTTP 路由（认证、上传、会议、项目、后台）
  core/         状态机、相似度、日志
  pipeline/     采集、转写、纪要、关联、归档、后台线程
  providers/    ASR / LLM 提供者接口与 mock、FunASR、OpenAI 实现
  services/     概览、会议、设置、账号
  storage/      SQLite 连接、迁移与仓储
  web/          Jinja2 模板与渲染
```

## 安全说明

- 本项目面向**内网私有化部署**，默认不提供 HTTPS、多租户隔离与公网防护。请勿直接暴露到公网；如需公网访问，请置于反向代理与身份认证之后。
- `.env`、`data/`、`site/`、`logs/`、`models/` 均已在 `.gitignore` 中排除，请勿把它们提交到仓库。
- 大模型 API Key 只保存在 `.env` 或本地数据库设置中，不会下发到浏览器。
- 发现安全问题请按 [SECURITY.md](SECURITY.md) 私下报告，不要开公开 Issue。

## 参与贡献

欢迎提交 Issue 与 Pull Request，请先阅读 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 许可证

[MIT](LICENSE)
