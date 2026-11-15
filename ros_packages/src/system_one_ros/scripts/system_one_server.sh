#!/usr/bin/env bash
# Локальный контейнер system-one-rknn под Kev-0.8B из GHCR (NPU RK3588), порт 18477.
#
#   scripts/system_one_server.sh pull      # скачать образ из GHCR
#   scripts/system_one_server.sh run       # запустить контейнер (kev, NPU, порт 18477)
#   scripts/system_one_server.sh wait      # ждать /health после загрузки модели
#   scripts/system_one_server.sh health    # GET /health
#   scripts/system_one_server.sh status    # состояние контейнера
#   scripts/system_one_server.sh logs      # follow логов
#   scripts/system_one_server.sh stop      # остановить и удалить контейнер
#
# Env: IMAGE, CONTAINER, PORT, BIND_ADDR, MODELS, KEV_MODELS_DIR, SYSTEM_ONE_ENGINE.
set -euo pipefail

IMAGE="${IMAGE:-ghcr.io/shiwarai/system-one-rknn:rk3588-main}"
CONTAINER="${CONTAINER:-system-one-rknn-kev}"
PORT="${PORT:-18477}"
BIND_ADDR="${BIND_ADDR:-127.0.0.1}"
MODELS="${MODELS:-kev}"
KEV_MODELS_DIR="${KEV_MODELS_DIR:-/home/orangepi/models/kev-0.8b-rknn}"
SYSTEM_ONE_ENGINE="${SYSTEM_ONE_ENGINE:-npu}"
WAIT_SEC="${WAIT_SEC:-600}"

usage() {
  sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
}

cmd_pull() {
  docker pull "$IMAGE"
}

cmd_run() {
  if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
    echo "образа $IMAGE нет, скачиваю..." >&2
    docker pull "$IMAGE"
  fi
  if [ ! -d "$KEV_MODELS_DIR" ]; then
    echo "нет каталога KEV_MODELS_DIR=$KEV_MODELS_DIR (скачай kev-0.8b-rknn)" >&2
    exit 2
  fi

  local devices=()
  local dev
  for dev in /dev/dri /dev/dma_heap /dev/mpp_service /dev/rga; do
    if [ -e "$dev" ]; then
      devices+=(--device "$dev")
    else
      echo "предупреждение: $dev отсутствует — NPU-инференс не заведётся" >&2
    fi
  done

  if docker ps -a --format '{{.Names}}' | grep -qx "$CONTAINER"; then
    docker rm -f "$CONTAINER" >/dev/null
  fi
  docker run -d --name "$CONTAINER" --restart unless-stopped \
    "${devices[@]}" \
    -e PORT="$PORT" \
    -e SYSTEM_ONE_ENGINE="$SYSTEM_ONE_ENGINE" \
    -e MODELS="$MODELS" \
    -p "${BIND_ADDR}:${PORT}:${PORT}" \
    -v "${KEV_MODELS_DIR}:/models/kev:ro" \
    "$IMAGE" >/dev/null
  echo "запущен $CONTAINER: порт $PORT, MODELS=$MODELS, kev: $KEV_MODELS_DIR"
  echo "health: curl -fsS http://127.0.0.1:${PORT}/health"
  echo "ожидание загрузки модели: $0 wait"
}

cmd_wait() {
  local deadline=$((SECONDS + WAIT_SEC))
  echo "жду http://127.0.0.1:${PORT}/health до ${WAIT_SEC} с..."
  while [ "$SECONDS" -lt "$deadline" ]; do
    if curl -fsS "http://127.0.0.1:${PORT}/health" 2>/dev/null; then
      echo
      return 0
    fi
    sleep 2
  done
  echo "таймаут ожидания /health; последние логи:" >&2
  docker logs --tail 50 "$CONTAINER" >&2 || true
  return 1
}

cmd_health() {
  curl -fsS "http://127.0.0.1:${PORT}/health"
  echo
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

cmd_status() {
  docker ps -a --filter "name=^/${CONTAINER}$" \
    --format '{{.Names}}  {{.Status}}  {{.Image}}  {{.Ports}}'
}

case "${1:-}" in
  pull) cmd_pull ;;
  run) cmd_run ;;
  wait) cmd_wait ;;
  health) cmd_health ;;
  stop) cmd_stop ;;
  logs) cmd_logs ;;
  status) cmd_status ;;
  *) usage; exit 1 ;;
esac
