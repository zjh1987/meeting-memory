#!/bin/bash
# 开机时确保 /dev/nvidia* 存在，避免 NAS 重启后容器因设备节点缺失无法启动。
set -e
cat > /etc/systemd/system/nvidia-devices.service <<'EOF'
[Unit]
Description=Create NVIDIA device nodes for containers
After=systemd-modules-load.service
Before=docker.service

[Service]
Type=oneshot
ExecStart=/usr/bin/nvidia-modprobe -c 0 -u
ExecStartPost=/usr/bin/nvidia-smi -L
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable nvidia-devices.service
systemctl restart nvidia-devices.service
systemctl status --no-pager nvidia-devices.service | head -15
