#!/bin/bash
# 在 NAS 宿主机安装 nvidia-container-toolkit 并配置 Docker。
# 仅在用户明确授权后执行；Docker 已开启 live-restore，重启时应尽量不影响现有容器。
set -o pipefail
BACKUP=/vol1/meeting-memory/daemon.json.bak
cp /etc/docker/daemon.json "${BACKUP}"

set -e
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
  | gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
  | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
  > /etc/apt/sources.list.d/nvidia-container-toolkit.list
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y nvidia-container-toolkit
nvidia-ctk runtime configure --runtime=docker --set-as-default=false

systemctl restart docker
sleep 8
if ! docker info >/dev/null 2>&1; then
  echo "docker restart failed, restoring daemon.json"
  cp "${BACKUP}" /etc/docker/daemon.json
  systemctl restart docker
  exit 1
fi

echo "runtimes:"
docker info --format '{{json .Runtimes}}'
echo "running_containers: $(docker ps -q | wc -l)"
