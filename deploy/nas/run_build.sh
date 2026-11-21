#!/bin/bash
# 后台构建 GPU 版应用镜像，日志写入 build.log。
cd /vol1/meeting-memory || exit 1
nohup docker compose build > build.log 2>&1 &
echo "build_started pid=$!"
