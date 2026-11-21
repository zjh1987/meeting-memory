#!/bin/bash
# 在 NAS 宿主环境中安装与内核模块版本一致的 NVIDIA 用户态驱动。
# 仅安装用户态：不动内核模块、DRM 与 OpenGL 文件，降低对 NAS 显示/转码的影响。
set -o pipefail
cd /vol1/meeting-memory || exit 1
RUN_FILE=NVIDIA-Linux-x86_64-580.142.run
LOG=nvidia-install.log
sh "./${RUN_FILE}" \
  --no-kernel-module \
  --no-drm \
  --no-opengl-files \
  --no-x-check \
  --silent > "${LOG}" 2>&1
code=$?
echo "installer_exit=${code}"
tail -40 "${LOG}" 2>/dev/null
exit "${code}"
