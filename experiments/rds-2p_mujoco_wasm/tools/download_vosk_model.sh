#!/usr/bin/env bash
# Скачивает русскую модель Vosk для браузерного распознавания в models/stt/
# (vosk-browser грузит её как tar.gz). Повторный запуск — no-op.
set -euo pipefail
cd "$(dirname "$0")/.."
DIR="models/stt"; NAME="vosk-model-small-ru-0.22"
mkdir -p "$DIR"
if [[ -s "$DIR/vosk-ru-small.tar.gz" ]]; then echo "готово: $DIR/vosk-ru-small.tar.gz"; exit 0; fi
echo "скачиваю https://alphacephei.com/vosk/models/$NAME.zip (~46 МБ)…"
curl -fL --retry 3 -o "$DIR/v.zip" "https://alphacephei.com/vosk/models/$NAME.zip"
cd "$DIR" && unzip -q v.zip && rm v.zip && tar -czf vosk-ru-small.tar.gz "$NAME" && rm -rf "$NAME"
echo "готово: $(pwd)/vosk-ru-small.tar.gz"
