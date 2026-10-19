#!/usr/bin/env bash
# Выгрузка артефактов Laya в models/laya (PLAN.md 7):
#   - tokenizer.json/temperature.json — из HF ShiWarai/laya-multilingual-rknn;
#   - ONNX-граф — результат tools/export_onnx.py (его нет на HF в готовом виде).
#
# Использование:
#   bash tools/download_models.sh            # только tokenizer/temperature
#   MODEL_REPO=ShiWarai/laya-multilingual-onnx bash tools/download_models.sh  # если опубликуете ONNX
set -euo pipefail

cd "$(dirname "$0")/.."
DEST="models/laya"
mkdir -p "$DEST"

HF_REPO="${MODEL_REPO:-ShiWarai/laya-multilingual-rknn}"

fetch() { # fetch <file>
  local name="$1"
  if [[ -s "$DEST/$name" ]]; then
    echo "уже есть: $DEST/$name ($(du -h "$DEST/$name" | cut -f1))"
    return
  fi
  echo "скачиваю $name из $HF_REPO …"
  if command -v huggingface-cli >/dev/null 2>&1; then
    huggingface-cli download "$HF_REPO" "$name" --local-dir "$DEST"
  else
    curl -fL --retry 3 -o "$DEST/$name" "https://huggingface.co/$HF_REPO/resolve/main/$name"
  fi
}

fetch tokenizer.json
fetch temperature.json

if [[ -n "${MODEL_FILE:-}" ]]; then
  fetch "$MODEL_FILE"
fi

if [[ ! -s "$DEST/manifest.json" ]]; then
  if [[ -s "$DEST/laya_multilingual_seq512.onnx" ]]; then
    cat > "$DEST/manifest.json" <<'EOF'
{
  "file": "laya_multilingual_seq512.onnx",
  "inputs": "int32",
  "tokenizer": "tokenizer.json",
  "temperature": "temperature.json",
  "seq": 512,
  "kmax": 64
}
EOF
    echo "manifest.json создан по умолчанию"
  else
    echo
    echo "ONNX-графа нет. Соберите его на x86 (см. tools/export_onnx.py):"
    echo "  python3.10 -m venv .venv && . .venv/bin/activate"
    echo "  pip install torch --index-url https://download.pytorch.org/whl/cpu"
    echo "  pip install 'laya==0.3.20' 'transformers==5.17.0' onnx"
    echo "  python tools/export_onnx.py --fp16"
  fi
fi

ls -la "$DEST"
