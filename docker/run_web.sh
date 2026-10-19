#!/usr/bin/env bash
# Запуск веб-приложения мастер-класса: http://localhost:8080
#
#   docker/run_web.sh                     # порт 8080
#   PORT=9000 docker/run_web.sh           # другой порт
#   NLU_UPSTREAM_URL=http://…  docker/run_web.sh   # прокси внешнего NLU (serve.py)
#
# Docker Desktop в Windows/WSL: порт публикуется на localhost хоста.
# Для доступа с других устройств по сети нужен https (микрофон = secure context):
#   docker run --rm -p 8443:8080 rds2p/web:latest \
#     python3 tools/serve.py --host 0.0.0.0 --port 8080 --https
set -euo pipefail

IMAGE="${IMAGE:-rds2p/web:latest}"
PORT="${PORT:-8080}"

ARGS=(docker run --rm -p "${PORT}:8080" --name rds2p-web)
[ -n "${NLU_UPSTREAM_URL:-}" ] && ARGS+=(-e "NLU_UPSTREAM_URL=${NLU_UPSTREAM_URL}")
if [ -t 0 ]; then ARGS+=(-it); fi

echo "Панда: http://localhost:${PORT}/"
exec "${ARGS[@]}" "$IMAGE"