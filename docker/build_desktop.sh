#!/usr/bin/env bash
# Тонкая обёртка: вся логика (prepare контекста + docker build) живёт в
# ros_packages/scripts/build_for_desktop.sh. Внешний API сохранён:
#   ./docker/build_desktop.sh                → --docker  (prepare + docker build)
#   PREPARE_ONLY=1 ./docker/build_desktop.sh → --prepare-only (для CI deploy.yml)
# Env: IMAGE — как раньше.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
if [ "${PREPARE_ONLY:-0}" = "1" ]; then
    exec bash "$ROOT_DIR/ros_packages/scripts/build_for_desktop.sh" --prepare-only "$@"
else
    exec bash "$ROOT_DIR/ros_packages/scripts/build_for_desktop.sh" --docker "$@"
fi
