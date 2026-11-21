#!/usr/bin/env bash
# 内网离线安装（Linux）。在解压后的离线包目录内执行：
#   sudo APP_DIR=/opt/meeting-memory ./install.sh
set -euo pipefail

BUNDLE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${APP_DIR:-/opt/meeting-memory}"
PYTHON="${PYTHON:-python3}"

[ -d "$BUNDLE_DIR/wheels" ] || { echo "缺少 wheels/ 目录，离线包不完整"; exit 1; }
command -v "$PYTHON" >/dev/null || {
  echo "未找到 $PYTHON，请先离线安装 Python 3.10"; exit 1; }

echo "安装到：$APP_DIR"
mkdir -p "$APP_DIR"

for item in app config deploy requirements.txt requirements-asr.txt .env.example; do
  rm -rf "$APP_DIR/$item"
  cp -r "$BUNDLE_DIR/$item" "$APP_DIR/$item"
done
if [ -d "$BUNDLE_DIR/models" ]; then
  mkdir -p "$APP_DIR/models"
  cp -r "$BUNDLE_DIR/models/." "$APP_DIR/models/"
fi
if [ -d "$BUNDLE_DIR/tools/ffmpeg" ]; then
  mkdir -p "$APP_DIR/tools"
  cp -r "$BUNDLE_DIR/tools/." "$APP_DIR/tools/"
  chmod +x "$APP_DIR/tools/ffmpeg/bin/"* 2>/dev/null || true
  export PATH="$APP_DIR/tools/ffmpeg/bin:$PATH"
fi

"$PYTHON" -m venv "$APP_DIR/.venv" || {
  echo "创建虚拟环境失败：请先安装 python3-venv"; exit 1; }
"$APP_DIR/.venv/bin/python" -m pip install --no-index \
  --find-links "$BUNDLE_DIR/wheels" \
  -r "$APP_DIR/requirements.txt" -r "$APP_DIR/requirements-asr.txt"

[ -f "$APP_DIR/.env" ] || cp "$APP_DIR/.env.example" "$APP_DIR/.env"
mkdir -p "$APP_DIR/data" "$APP_DIR/site" "$APP_DIR/logs"

cat <<EOF

安装完成。后续步骤：
1. 编辑 $APP_DIR/.env（至少设置 APP_PASSWORD、COOKIE_SECRET、ASR_BACKEND、LLM_*）
2. 安装服务：
   sudo cp $APP_DIR/deploy/systemd/mm.service /etc/systemd/system/
   sudo systemctl daemon-reload && sudo systemctl enable --now mm
3. 配置 Nginx：
   sudo cp $APP_DIR/deploy/nginx/mm.conf /etc/nginx/conf.d/
   sudo nginx -t && sudo systemctl reload nginx
4. FFmpeg 路径：$APP_DIR/tools/ffmpeg/bin（未打包时需自行安装并加入 PATH）
5. 前台试运行：
   cd $APP_DIR && .venv/bin/python -m uvicorn app.main:create_app \\
     --factory --env-file .env --host 127.0.0.1 --port 8000 --workers 1
EOF
