#!/bin/bash
# Скачивает и распаковывает onnxruntime SDK 1.19.2 в src/rds_2p_inference/external_lib.
# Единственный источник этой логики: её вызывают build_for_robot.sh,
# build_for_desktop.sh, docker/build_robot.sh и docker/build_desktop.sh (prepare).
# Архитектура берётся от машины-хоста (uname -m) — в CI это нативные runner'ы по arch.
# Идемпотентен: если SDK уже на месте — ничего не делает.
set -eu
WS="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
EL="$WS/src/rds_2p_inference/external_lib"
A="$(uname -m)"
case "$A" in
  x86_64)          ORT=onnxruntime-linux-x64-1.19.2 ;;
  aarch64|arm64)   ORT=onnxruntime-linux-aarch64-1.19.2 ;;
  *) echo "❌ unsupported arch: $A" >&2; exit 1 ;;
esac
if [ -d "$EL/$ORT" ]; then
  echo "ℹ️ OnnxRuntime уже установлен: $ORT"
  exit 0
fi
echo "📥 Скачиваем OnnxRuntime 1.19.2 ($A)..."
mkdir -p "$EL"
cd "$EL"
TGZ="$ORT.tgz"
if [ ! -f "$TGZ" ]; then
  curl -L -o "$TGZ" "https://github.com/microsoft/onnxruntime/releases/download/v1.19.2/$ORT.tgz"
fi
tar -xf "$TGZ"
rm -f "$TGZ"
echo "✅ OnnxRuntime установлен в $EL/$ORT"
