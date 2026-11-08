# models/laya — артефакты Laya (не в git)

Сюда кладутся файлы браузерного NLU:

- `laya_multilingual_seq512.onnx` (fp16, WebGPU) и/или `*.int8.onnx` (WASM);
- `tokenizer.json` (mmBERT, 256k);
- `temperature.json`;
- `manifest.json` — опись: `{"file": "...", "inputs": "int32", "tokenizer": "tokenizer.json", "temperature": "temperature.json"}`.

Как получить — см. `tools/download_models.sh` и `tools/export_onnx.py` (PLAN.md раздел 7).
Если файлов нет — приложение работает в быстром режиме (keywords) и это не ошибка.
