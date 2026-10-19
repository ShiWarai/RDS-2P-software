#!/usr/bin/env bash
# Сборка веб-образа мастер-класса («Панда» в браузере, без ROS). Конвенции как
# у build_desktop.sh: контекст готовится здесь, docker build — отдельно.
#
# Режимы:
#   (без аргументов) / --docker     подготовить контекст и собрать образ
#   --prepare-only | PREPARE_ONLY=1 подготовить контекст и выйти (для CI; контекст
#                                   остаётся в build/web-context)
#
# Что делает prepare:
#   1) node_modules приложения (он в .gitignore — в чистом клоне его нет,
#      ставится через npm ci/install по package.json + package-lock.json);
#   2) стейджинг контекста build/web-context: приложение без тяжёлых моделей
#      (их качает Dockerfile), канонические obj-меши и ONNX-политика.
#
#   docker/build_web.sh                  # → rds2p/web:latest
#   IMAGE=rds2p/web:test docker/build_web.sh
#   WITH_MODELS=0 docker/build_web.sh    # лёгкий образ без Laya/Vosk
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
APP_DIR="$ROOT_DIR/experiments/rds-2p_mujoco_wasm"
STAGE="$ROOT_DIR/build/web-context"
IMAGE="${IMAGE:-rds2p/web:latest}"

MODE=build
case "${1:-}" in
    --prepare-only) MODE=prepare ;;
    --docker | "") ;;
    *)
        echo "Использование: $0 [--docker | --prepare-only]" >&2
        exit 1
        ;;
esac
[ "${PREPARE_ONLY:-0}" = "1" ] && MODE=prepare
[ "$#" -gt 0 ] && shift || true

[ -d "$APP_DIR" ] || { echo "нет $APP_DIR" >&2; exit 1; }

# 1) зависимости приложения (для CI-клона; локально node_modules уже есть)
if [ ! -d "$APP_DIR/node_modules" ]; then
    echo "==> ставлю зависимости приложения (node_modules нет)"
    if [ -f "$APP_DIR/package-lock.json" ]; then
        npm ci --prefix "$APP_DIR"
    else
        npm install --prefix "$APP_DIR"
    fi
fi

# 2) стейджинг контекста
echo "==> готовлю контекст: $STAGE"
rm -rf "$STAGE"
mkdir -p "$STAGE/experiments" \
         "$STAGE/urdf_src/export/rds-2p/meshes/obj" \
         "$STAGE/ros_packages/src/rds_2p_inference"

tar -C "$ROOT_DIR/experiments" \
    --exclude='rds-2p_mujoco_wasm/models' \
    --exclude='rds-2p_mujoco_wasm/.test' \
    --exclude='rds-2p_mujoco_wasm/.certs' \
    --exclude='rds-2p_mujoco_wasm/tools/.venv' \
    --exclude='rds-2p_mujoco_wasm/tools/__pycache__' \
    --exclude='.playwright-mcp' \
    -cf - rds-2p_mujoco_wasm | tar -C "$STAGE/experiments" -xf -

cp -a "$ROOT_DIR/urdf_src/export/rds-2p/meshes/obj/." "$STAGE/urdf_src/export/rds-2p/meshes/obj/"
cp -a "$ROOT_DIR/ros_packages/src/rds_2p_inference/models/." "$STAGE/ros_packages/src/rds_2p_inference/models/"

if [ "$MODE" = "prepare" ]; then
    echo "✅ Контекст web-сборки подготовлен (--prepare-only/PREPARE_ONLY=1) — docker build пропущен"
    exit 0
fi

command -v docker >/dev/null || { echo "нужен docker (в WSL включите интеграцию Docker Desktop)" >&2; exit 1; }

echo "🐳 docker build -f docker/web.Dockerfile -t $IMAGE $STAGE"
docker build -f "$SCRIPT_DIR/web.Dockerfile" -t "$IMAGE" \
    --build-arg "WITH_MODELS=${WITH_MODELS:-1}" "$@" "$STAGE"
rm -rf "$STAGE"

echo "✅ Образ $IMAGE собран. Запуск: docker/run_web.sh"
echo "   (лёгкий вариант без моделей: WITH_MODELS=0 docker/build_web.sh)"