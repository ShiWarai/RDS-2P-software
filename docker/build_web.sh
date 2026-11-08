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
# APP_DIR — каталог приложения-источника. По умолчанию — основной; для
# вариантов-песочниц (experiments/variants/<имя>/) передаётся APP_DIR=<папка>,
# тогда из этой папки собирается собственный образ (см. TASKS.md).
APP_DIR="${APP_DIR:-$ROOT_DIR/experiments/rds-2p_mujoco_wasm}"
STAGE="$ROOT_DIR/build/web-context"
# Контекст сборки всегда кладётся под именем rds-2p_mujoco_wasm/ (Dockerfile
# ссылается на этот путь), независимо от имени исходной папки.
CTX_APP="rds-2p_mujoco_wasm"
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
mkdir -p "$STAGE/experiments/$CTX_APP" \
         "$STAGE/urdf_src/export/rds-2p/meshes/obj" \
         "$STAGE/ros_packages/src/rds_2p_inference"

# Прунинг node_modules: браузер грузит только то, что реально прописано в
# index.html/importmap и в src/ (проверено по графу ссылок). Всё остальное —
# мёртвый вес контекста и образа (~180 МБ): карты исходников, неиспользуемые
# ORT-варианты, three/src+examples, blockly-генераторы/языки, jsdom/undici.
NM="$CTX_APP/node_modules"
# Стейджим ИМЕННО содержимое APP_DIR (относительные пути ./...) в фиксированный
# контекстный путь experiments/$CTX_APP — поэтому любой вариант-папка собирается
# в тот же Dockerfile без правок.
tar -C "$APP_DIR" \
    --exclude='./models/laya' \
    --exclude='./models/stt' \
    --exclude='./.test' \
    --exclude='./.certs' \
    --exclude='./tools/.venv' \
    --exclude='./tools/__pycache__' \
    --exclude='./.playwright-mcp' \
    --exclude='*.map' \
    --exclude='./node_modules/onnxruntime-web/dist/ort-wasm-simd-threaded.jsep*' \
    --exclude='./node_modules/onnxruntime-web/dist/ort-wasm-simd-threaded.jspi*' \
    --exclude='./node_modules/onnxruntime-web/dist/ort.all*' \
    --exclude='./node_modules/onnxruntime-web/dist/ort.webgl*' \
    --exclude='./node_modules/onnxruntime-web/dist/ort.jspi*' \
    --exclude='./node_modules/onnxruntime-web/dist/ort.min.*' \
    --exclude='./node_modules/three' \
    --exclude='./node_modules/blockly' \
    --exclude='./node_modules/jsdom' \
    --exclude='./node_modules/undici' \
    --exclude='./node_modules/@types' \
    -cf - . | tar -C "$STAGE/experiments/$CTX_APP" -xf -

# Возвращаем из вырезанного то, что приложение действительно использует:
#   three: importmap `three` → build/three.module.js (+ его импорт three.core.js),
#          `three/addons/controls/OrbitControls.js` (импортирует только 'three');
#   blockly: blockly.min.js + русская локаль + media (иконки/звуки полей).
mkdir -p "$STAGE/experiments/$NM/three/build" \
         "$STAGE/experiments/$NM/three/examples/jsm/controls" \
         "$STAGE/experiments/$NM/blockly/msg"
cp "$APP_DIR/node_modules/three/build/three.module.js" \
   "$APP_DIR/node_modules/three/build/three.core.js" \
   "$STAGE/experiments/$NM/three/build/"
cp "$APP_DIR/node_modules/three/examples/jsm/controls/OrbitControls.js" \
   "$STAGE/experiments/$NM/three/examples/jsm/controls/"
cp "$APP_DIR/node_modules/blockly/blockly.min.js" "$STAGE/experiments/$NM/blockly/"
cp "$APP_DIR/node_modules/blockly/msg/ru.js" "$STAGE/experiments/$NM/blockly/msg/"
cp -a "$APP_DIR/node_modules/blockly/media" "$STAGE/experiments/$NM/blockly/media"

cp -a "$ROOT_DIR/urdf_src/export/rds-2p/meshes/obj/." "$STAGE/urdf_src/export/rds-2p/meshes/obj/"
cp -a "$ROOT_DIR/ros_packages/src/rds_2p_inference/models/." "$STAGE/ros_packages/src/rds_2p_inference/models/"

echo "==> контекст: $(du -sh "$STAGE" | cut -f1)"

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