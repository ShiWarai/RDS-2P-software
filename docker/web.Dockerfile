# Образ веб-приложения мастер-класса «Панда» (RDS-2P).
#
# Внутри — статическое веб-приложение с браузерным симулятором: MuJoCo-WASM,
# нейросетевая походка (ONNX-политика), классификатор фраз Laya-ONNX и офлайн-голос
# Vosk. ROS на хосте и в контейнере НЕ нужен — всё считает браузер клиента,
# контейнер только раздаёт файлы (serve.py со COOP/COEP и кэш-заголовками).
#
# Сборка — через docker/build_web.sh (он готовит контекст build/web-context), или вручную:
#   PREPARE_ONLY=1 docker/build_web.sh
#   docker build -f docker/web.Dockerfile -t rds2p/web:latest build/web-context
# Запуск:
#   docker/run_web.sh          # http://localhost:8080
#
# Laya-модель (646 МБ) и модель Vosk (~46 МБ) скачиваются на этапе сборки.
# Лёгкая сборка без моделей:  WITH_MODELS=0 docker/build_web.sh
# (симулятор и политика работают, «Модель ИИ»/голос будут недоступны).

FROM python:3.12-slim
ARG DEBIAN_FRONTEND=noninteractive
ARG WITH_MODELS=1
ARG LAYA_AUX_REPO=ShiWarai/laya-multilingual-rknn
ARG LAYA_MODEL_URL=https://huggingface.co/mizchi/laya-multilingual-onnx/resolve/main/model.onnx

RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl unzip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Веб-приложение целиком, включая вендорные библиотеки node_modules
# (mujoco-js, onnxruntime-web, vosk-browser, blockly) — npm на сборке не нужен.
COPY experiments/rds-2p_mujoco_wasm/ /app/experiments/rds-2p_mujoco_wasm/

# Канонические obj-меши: serve.py отдаёт их по /assets/scenes/meshes/*.obj
# (см. ros_packages/scripts/build_for_desktop.sh — тот же канон, без копий).
COPY urdf_src/export/rds-2p/meshes/obj/ /app/urdf_src/export/rds-2p/meshes/obj/

# ONNX-политика ходьбы из rospkg rds_2p_inference: /models/policy/*.
COPY ros_packages/src/rds_2p_inference/models/ /app/ros_packages/src/rds_2p_inference/models/

WORKDIR /app/experiments/rds-2p_mujoco_wasm
RUN set -eux; \
    if [ "$WITH_MODELS" = "1" ]; then \
      mkdir -p models/laya; \
      curl -fL --retry 3 -o models/laya/tokenizer.json \
        "https://huggingface.co/${LAYA_AUX_REPO}/resolve/main/tokenizer.json"; \
      curl -fL --retry 3 -o models/laya/temperature.json \
        "https://huggingface.co/${LAYA_AUX_REPO}/resolve/main/temperature.json"; \
      curl -fL --retry 3 -o models/laya/model.onnx "${LAYA_MODEL_URL}"; \
      printf '{\n  "file": "model.onnx",\n  "inputs": "int64",\n  "tokenizer": "tokenizer.json",\n  "temperature": "temperature.json",\n  "seq": 512,\n  "kmax": 64\n}\n' > models/laya/manifest.json; \
      bash tools/download_vosk_model.sh; \
    fi

ENV PORT=8080
EXPOSE 8080
# Микрофон в браузере требует защищённого контекста: на localhost он есть;
# для доступа по сети запускайте с TLS (serve.py --https или reverse-proxy).
CMD ["python3", "tools/serve.py", "--host", "0.0.0.0", "--port", "8080"]