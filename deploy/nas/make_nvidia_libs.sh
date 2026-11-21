#!/bin/bash
# 为容器准备 NVIDIA 用户态库的只读目录（符号链接，不复制大文件）。
set -e
TARGET=/vol1/meeting-memory/nvidia-libs
mkdir -p "${TARGET}"
rm -f "${TARGET}"/*.so*
for file in /usr/lib/x86_64-linux-gnu/libcuda.so* \
            /usr/lib/x86_64-linux-gnu/libnvidia*.so*; do
  [ -e "${file}" ] && cp -L "${file}" "${TARGET}/$(basename "${file}")"
done
du -sh "${TARGET}"
ls -l "${TARGET}" | head -10
