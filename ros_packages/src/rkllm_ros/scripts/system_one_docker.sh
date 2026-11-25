#!/usr/bin/env bash
# Тонкая обёртка вокруг docker для сервиса system-one-rknn (образ из GHCR).
#
#   scripts/system_one_docker.sh pull      # скачать образ
#   scripts/system_one_docker.sh run       # запустить контейнер (NPU-девайсы, порт, kev-веса)
#   scripts/system_one_docker.sh health    # GET /health
#   scripts/system_one_docker.sh logs      # follow логов
#   scripts/system_one_docker.sh status    # состояние контейнера
#   scripts/system_one_docker.sh stop      # удалить контейнер
#
# Env: IMAGE, CONTAINER, PORT, MODELS, KEV_MODELS_DIR
set -euo pipefail

IMAGE="${IMAGE:-ghcr.io/shiwarai/system-one-rknn:rk3588-main}"
CONTAINER="${CONTAINER:-system-one-rknn}"
PORT="${PORT:-8080}"
MODELS="${MODELS:-kev}"
KEV_MODELS_DIR="${KEV_MODELS_DIR:-/home/orangepi/models/kev-0.8b-rknn}"

usage() {
  sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'
}

cmd_pull() {
  docker pull "$IMAGE"
}

cmd_run() {
  if [ ! -d "$KEV_MODELS_DIR" ]; then
    echo "нет каталога KEV_MODELS_DIR=$KEV_MODELS_DIR (скачай kev-0.8b-rknn)" >&2
    exit 2
  fi
  for dev in /dev/dri /dev/dma_heap /dev/mpp_service /dev/rga; do
    if [ ! -e "$dev" ]; then
      echo "предупреждение: $dev отсутствует — NPU-инференс не заведётся" >&2
    fi
  done
  if docker ps -a --format '{{.Names}}' | grep -qx "$CONTAINER"; then
    docker rm -f "$CONTAINER" >/dev/null
  fi
  docker run -d --name "$CONTAINER" --restart unless-stopped \
    --device /dev/dri --device /dev/dma_heap \
    --device /dev/mpp_service --device /dev/rga \
    -e PORT="$PORT" -e SYSTEM_ONE_ENGINE=npu -e MODELS="$MODELS" \
    -p "${PORT}:${PORT}" \
    -v "${KEV_MODELS_DIR}:/models/kev:ro" \
    "$IMAGE" >/dev/null
  echo "запущен $CONTAINER: порт $PORT, MODELS=$MODELS, kev: $KEV_MODELS_DIR"
  echo "health: curl -fsS http://127.0.0.1:${PORT}/health"
}

cmd_stop() {
  if docker rm -f "$CONTAINER" >/dev/null 2>&1; then
    echo "остановлен и удалён $CONTAINER"
  else
    echo "контейнер $CONTAINER не найден"
  fi
}

cmd_logs() {
  docker logs -f --tail 100 "$CONTAINER"
}

cmd_health() {
  curl -fsS "http://127.0.0.1:${PORT}/health"
  echo
}

cmd_status() {
  docker ps -a --filter "name=^/${CONTAINER}$" \
    --format '{{.Names}}  {{.Status}}  {{.Image}}'
}

case "${1:-}" in
  pull) cmd_pull ;;
  run) cmd_run ;;
  stop) cmd_stop ;;
  logs) cmd_logs ;;
  health) cmd_health ;;
  status) cmd_status ;;
  *) usage; exit 1 ;;
esac