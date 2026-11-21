#!/bin/bash
# 后台启动容器工具链安装，避免 SSH 会话结束导致中断。
nohup docker run --rm --privileged --pid=host --net=host --ipc=host --uts=host \
  -v /:/host nginx:latest \
  chroot /host /bin/bash /vol1/meeting-memory/install_toolkit_only.sh \
  > /vol1/meeting-memory/toolkit.log 2>&1 &
echo "started pid=$!"
