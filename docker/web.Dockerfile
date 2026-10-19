# Образ веб-приложения мастер-класса «Панда» (RDS-2P).
#
# Внутри — статическое веб-приложение с браузерным симулятором: MuJoCo-WASM,
# нейросетевая походка (ONNX-политика), классификатор фраз Laya-ONNX и офлайн-голос
# Vosk. ROS на хосте и в контейнере НЕ нужен — всё считает браузер клиента,
# контейнер только раздаёт файлы (serve.py: COOP/COEP, кэш-заголовки, HTTP/1.1
# keep-alive, предсжатые .gz, Range-докачка).
#
# Сборка — через docker/build_web.sh (он готовит контекст build/web-context), или вручную:
#   PREPARE_ONLY=1 docker/build_web.sh
#   docker build -f docker/web.Dockerfile -t rds2p/web:latest build/web-context
# Запуск:
#   docker/run_web.sh          # http://localhost:8080
#
# Laya-модель (646 МБ) и модель Vosk (~46 МБ) скачиваются в отдельной стадии
# `models`: её входы — только URL-ы и tools/download_vosk_model.sh, поэтому правки
# кода приложения не инвалидируют кэш загрузки. В рантайм-образ curl/unzip не
# попадают. Лёгкая сборка без моделей:  WITH_MODELS=0 docker/build_web.sh
# (симулятор и политика работают, «Модель ИИ»/голос будут недоступны).

# ── Стадия 1: скачивание моделей ──────────────────────────────────────────
FROM python:3.12-slim AS models
ARG DEBIAN_FRONTEND=noninteractive
ARG WITH_MODELS=1
ARG LAYA_AUX_REPO=ShiWarai/laya-multilingual-rknn
ARG LAYA_MODEL_URL=https://huggingface.co/mizchi/laya-multilingual-onnx/resolve/main/model.onnx

RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl unzip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /dl
COPY experiments/rds-2p_mujoco_wasm/tools/download_vosk_model.sh tools/download_vosk_model.sh
# Каталог models/ создаём всегда: с WITH_MODELS=0 стадия оставляет пустой каталог,
# и COPY в рантайм-стадию ниже не падает из-за отсутствующего источника.
RUN set -eux; \
    mkdir -p models/laya models/stt; \
    if [ "$WITH_MODELS" = "1" ]; then \
      curl -fL --retry 3 -o models/laya/tokenizer.json \
        "https://huggingface.co/${LAYA_AUX_REPO}/resolve/main/tokenizer.json"; \
      curl -fL --retry 3 -o models/laya/temperature.json \
        "https://huggingface.co/${LAYA_AUX_REPO}/resolve/main/temperature.json"; \
      curl -fL --retry 3 -o models/laya/model.onnx "${LAYA_MODEL_URL}"; \
      printf '{\n  "file": "model.onnx",\n  "inputs": "int64",\n  "tokenizer": "tokenizer.json",\n  "temperature": "temperature.json",\n  "seq": 512,\n  "kmax": 64\n}\n' > models/laya/manifest.json; \
      bash tools/download_vosk_model.sh; \
    fi

# ── Стадия 2: рантайм ─────────────────────────────────────────────────────
FROM python:3.12-slim

# .pyc не пишем (корень работающего контейнера может быть только для чтения)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080

WORKDIR /app

# Модели — первыми слоями: их не задевает обновление кода приложения
# (в контексте каталог models/ исключён, конфликтов с COPY ниже нет).
COPY --from=models /dl/models/ /app/experiments/rds-2p_mujoco_wasm/models/

# Веб-приложение целиком, включая вендорные библиотеки node_modules
# (mujoco-js, onnxruntime-web, vosk-browser, blockly) — npm на сборке не нужен.
COPY experiments/rds-2p_mujoco_wasm/ /app/experiments/rds-2p_mujoco_wasm/

# Канонические obj-меши: serve.py отдаёт их по /assets/scenes/meshes/*.obj
# (см. ros_packages/scripts/build_for_desktop.sh — тот же канон, без копий).
COPY urdf_src/export/rds-2p/meshes/obj/ /app/urdf_src/export/rds-2p/meshes/obj/

# ONNX-политика ходьбы из rospkg rds_2p_inference: /models/policy/*.
COPY ros_packages/src/rds_2p_inference/models/ /app/ros_packages/src/rds_2p_inference/models/

WORKDIR /app/experiments/rds-2p_mujoco_wasm

# Предсжатие статики (.gz-сиблинги): serve.py отдаёт их при Accept-Encoding: gzip.
# Больше всего выигрывают mujoco_wasm.js (11 МБ), ORT-wasm и obj-меши.
RUN python3 tools/precompress_assets.py . /app/urdf_src

# Непривилегированный пользователь: serve.py только читает файлы (644/755 хватает).
RUN useradd -m -u 10001 panda
USER panda

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD ["python3", "-c", "import urllib.request as u; u.urlopen('http://127.0.0.1:8080/', timeout=3)"]

# Микрофон в браузере требует защищённого контекста: на localhost он есть;
# для доступа по сети запускайте с TLS (serve.py --https или reverse-proxy).
CMD ["python3", "tools/serve.py", "--host", "0.0.0.0", "--port", "8080"]