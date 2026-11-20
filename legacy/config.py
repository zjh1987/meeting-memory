"""全局配置：目录、账号、模型接入方式。

全部通过环境变量覆盖，便于后续切到真实 ASR / 大模型。
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

DATA_DIR = BASE_DIR / "data"
INBOX_DIR = DATA_DIR / "inbox"        # 设备/手机落盘，可写入 .part
READY_DIR = DATA_DIR / "ready"        # 只有完整文件才会出现在这里
ARCHIVE_DIR = DATA_DIR / "archive"    # 处理完成的原始音频
DB_PATH = DATA_DIR / "app.db"
SITE_DIR = BASE_DIR / "site"          # 静态归档输出
TEMPLATE_DIR = BASE_DIR / "templates"

for _d in (DATA_DIR, INBOX_DIR, READY_DIR, ARCHIVE_DIR, SITE_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# 登录口令。生产环境务必改掉，并且换成真正的账号体系。
APP_PASSWORD = os.getenv("APP_PASSWORD", "demo1234")

# mock 表示不调用外部服务，用内置样例跑通全链路
ASR_PROVIDER = os.getenv("ASR_PROVIDER", "mock")      # mock | openai
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "mock")      # mock | openai
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
ASR_MODEL = os.getenv("ASR_MODEL", "whisper-1")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")

# 目录扫描间隔（秒）
SCAN_INTERVAL = 3
DEFAULT_PROJECT = "未归类"

AUDIO_SUFFIXES = {".m4a", ".mp3", ".wav", ".opus", ".aac", ".amr", ".flac"}
