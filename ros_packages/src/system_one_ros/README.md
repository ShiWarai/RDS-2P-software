# system_one_ros

ROS 2 (Humble) клиент HTTP API [system-one-rknn](https://github.com/ShiWarai/system-one-rknn): решения **Kev-0.8B** на NPU RK3588 (`choice` / `noul` / `score`) без генерации текста.

Пакет — только клиент. Сервер инференса поднимается отдельным контейнером из GHCR; для него выбран **нестандартный порт 18477**, чтобы не пересекаться с другими сервисами на 8080.

## Интерфейсы

| Интерфейс | Тип | Описание |
|-----------|-----|----------|
| `~/ask` | `llm_msgs_ros/srv/Ask` | Произвольное тело `POST /v1/systemone`: один или несколько вопросов, любые поля API |
| `~/health` | `std_srvs/srv/Trigger` | `GET /health`: `success`, модели и задержка в `message` |
| `~/server_ok` | `std_msgs/Bool` | Последний результат health-check (transient local) |
| `~/models` | `std_msgs/String` | JSON-массив моделей сервера (transient local) |

`Ask` принимает готовый JSON-объект с `model`, `state` и `questions`, поэтому один вызов покрывает и один вопрос, и пакет из нескольких — за один инференс. Поля `.srv`:

```
string request_json
---
bool success
string message
uint32 http_status
string response_json
uint32 latency_ms
```

Узел: **`system_one_client`**. Параметры: `server_url` (`http://127.0.0.1:18477`), `timeout_sec` (`30.0`), `health_timeout_sec` (`3.0`), `health_period_sec` (`10.0`, `0` — выключить).

Проверка здоровья без отдельного типа сообщения:

```bash
ros2 service call /system_one_client/health std_srvs/srv/Trigger '{}'
ros2 topic echo /system_one_client/models --qos-durability transient_local --once
```

## Сервер (Docker)

Образ из GHCR, локальная сборка не нужна:

```bash
ros2 run system_one_ros system_one_server.sh pull   # ghcr.io/shiwarai/system-one-rknn:rk3588-main
ros2 run system_one_ros system_one_server.sh run    # контейнер system-one-rknn-kev, порт 18477
ros2 run system_one_ros system_one_server.sh wait   # ждать /health после загрузки модели
ros2 run system_one_ros system_one_server.sh health
ros2 run system_one_ros system_one_server.sh status
ros2 run system_one_ros system_one_server.sh logs
ros2 run system_one_ros system_one_server.sh stop
```

`run` монтирует веса из `KEV_MODELS_DIR` (по умолчанию `/home/orangepi/models/kev-0.8b-rknn`) в `/models/kev:ro`, включает `MODELS=kev` и пробрасывает NPU-устройства `/dev/dri`, `/dev/dma_heap`, `/dev/mpp_service`, `/dev/rga`. Порт по умолчанию слушается только на `127.0.0.1`; для доступа из сети задайте `BIND_ADDR=0.0.0.0`.

Переменные скрипта: `IMAGE`, `CONTAINER` (`system-one-rknn-kev`), `PORT` (`18477`), `BIND_ADDR`, `MODELS`, `KEV_MODELS_DIR`, `SYSTEM_ONE_ENGINE`, `WAIT_SEC`.

## Сборка и запуск узла

```bash
cd ~/RDS-2P-software/ros_packages
source /opt/ros/humble/setup.bash
colcon build --packages-select system_one_ros --symlink-install
source install/setup.bash

ros2 launch system_one_ros system_one.launch.py
# другой сервер/порт:
# ros2 launch system_one_ros system_one.launch.py server_url:=http://127.0.0.1:18477
```

## Пример: три вопроса за один вызов

```bash
cat >/tmp/systemone_request.json <<'JSON'
{
  "model": "kev-0.8b",
  "state": "Продовый сервер базы данных упал, клиенты не могут оплатить счета, всё срочно.",
  "questions": {
    "intent": {
      "type": "choice",
      "instructions": "Classify the root cause domain.",
      "criteria": {
        "infrastructure": "Database, hardware, network, or server failures",
        "billing": "Invoices, payments, refunds"
      }
    },
    "is_urgent": {
      "type": "noul",
      "instructions": "Does this issue require immediate attention?"
    },
    "severity": {
      "type": "score",
      "instructions": "Rate the incident severity.",
      "criteria": ["Low", "Medium", "High"]
    }
  }
}
JSON

ros2 run system_one_ros example_ask --file /tmp/systemone_request.json
```

Ответ:

```json
{
  "success": true,
  "message": "ok",
  "http_status": 200,
  "latency_ms": 3251,
  "response": {
    "model": "kev-0.8b",
    "answers": {
      "intent": {
        "type": "choice",
        "choice": "infrastructure",
        "confidence": 0.9189,
        "probabilities": {"infrastructure": 0.9595, "billing": 0.0405}
      },
      "is_urgent": {"type": "noul", "noul": 0.8892},
      "severity": {
        "type": "score",
        "score": 1.5827,
        "confidence": 0.374,
        "legend": {"0": "Low", "1": "Medium", "2": "High"},
        "probabilities": {"0": 0.0735, "1": 0.2702, "2": 0.6562}
      }
    },
    "usage": {"input_tokens": 124, "output_tokens": 0}
  }
}
```

Другие формы вызова:

```bash
# JSON-строкой
ros2 run system_one_ros example_ask '{"model":"kev-0.8b","state":"…","questions":{"q":{"type":"noul"}}}'

# из stdin
cat /tmp/systemone_request.json | ros2 run system_one_ros example_ask

# напрямую через ROS-сервис (JSON без одинарных кавычек)
ros2 service call /system_one_client/ask llm_msgs_ros/srv/Ask \
  "{request_json: '{\"model\":\"kev-0.8b\",\"state\":\"…\",\"questions\":{\"q\":{\"type\":\"noul\"}}}'}"
```

`state` в `Ask` может быть строкой, объектом или массивом — сервер принимает все три формы. Все вопросы одного запроса используют один и тот же `state`; для разных состояний делайте отдельные вызовы.

## Ошибки

Валидация JSON, HTTP-ошибки и таймауты возвращаются как `success=false`, `message` и `http_status` (0 — ответа не было). При HTTP-ошибке `response_json` всё равно содержит тело ответа сервера.

## Замечания

- `system-one-rknn` использует `MODELS=kev`; другие модели (`laya`) этим пакетом не запрашиваются, но `model` в JSON можно переопределить.
- Health-check по умолчанию раз в 10 с; `~/server_ok` и `~/models` обновляются только при изменении состояния.
- Сервер сериализует инференс внутри контейнера; параллельные `Ask`-вызовы встают в очередь на его стороне.
- Если на 8080 уже работает другой экземпляр `system-one-rknn`, этот пакет его не трогает: контейнер называется `system-one-rknn-kev` и слушает 18477.