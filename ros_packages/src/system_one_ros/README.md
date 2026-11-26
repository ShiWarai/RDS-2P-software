# system_one_ros

ROS 2 (Humble) сервер решений **Kev-0.8B** на NPU RK3588 (`choice` / `noul` / `score`)
без генерации текста. По умолчанию Kev/RKLLM работает **внутри ROS 2 ноды**:
ни Docker, ни HTTP.

## Интерфейсы

| Интерфейс | Тип | Описание |
|-----------|-----|----------|
| `/system_one/ask` | `llm_msgs_ros/srv/Ask` | JSON `{model, state, questions}` — как `POST /v1/systemone` |
| `/system_one/health` | `std_srvs/srv/Trigger` | `success`, модели и каталог модели в `message` |

`Ask` принимает один или несколько вопросов за вызов. Поля `.srv`:

```
string request_json
---
bool success
string message
uint32 http_status
string response_json
uint32 latency_ms
```

## Native-узел

Узел **`system_one`** сам грузит `KevEngine` из
`system-one-rknn` и вызывает RKLLM напрямую. Параметры:

| Параметр | По умолчанию |
|----------|--------------|
| `model_root` | `/home/orangepi/models/kev-0.8b-rknn` |
| `rkllm_lib` | `/opt/npu/librkllmrt-1.3.1.so` |
| `rknpu_lib` | `/opt/npu/librknnrt-2.3.2.so` |
| `model` | `kev-0.8b` |

В `model_root` нужны `kev-0.8b-w8a8-opt0-ctx320.rkllm`, `tokenizer.json`,
`pointer.json`, `q_weight.npy`, `q_bias.npy`, `k_weight.npy`, `k_bias.npy`.

Сборка и запуск:

```bash
cd ~/RDS-2P-software/ros_packages
source /opt/ros/humble/setup.bash
colcon build --packages-select system_one_ros
source install/setup.bash
ros2 launch system_one_ros system_one.launch.py
```

Другие модель/библиотеки:

```bash
ros2 launch system_one_ros system_one.launch.py \
  model_root:=/path/to/kev rkllm_lib:=/path/to/librkllmrt.so
```

Проверка:

```bash
ros2 service call /system_one/health std_srvs/srv/Trigger '{}'
ros2 run system_one_ros example_ask '{"model":"kev-0.8b","state":"привет","questions":{"q":{"type":"noul"}}}'
```

## HTTP fallback

Для удалённого/старого сервера system-one-rknn оставлен HTTP-клиент:

```bash
ros2 launch system_one_ros system_one.launch.py \
  mode:=http server_url:=http://127.0.0.1:18477
```

Он создаёт те же `/system_one/ask` и `/system_one/health`, но внутри делает HTTP.
Локальный контейнер этим пакетом больше не поднимается.

## Пример: несколько вопросов за один вызов

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
    "is_urgent": {"type": "noul", "instructions": "Requires immediate attention?"},
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

Другие формы вызова:

```bash
ros2 run system_one_ros example_ask '{"model":"kev-0.8b","state":"…","questions":{"q":{"type":"noul"}}}'
cat /tmp/systemone_request.json | ros2 run system_one_ros example_ask
ros2 service call /system_one/ask llm_msgs_ros/srv/Ask \
  "{request_json: '{\"model\":\"kev-0.8b\",\"state\":\"…\",\"questions\":{\"q\":{\"type\":\"noul\"}}}'}"
```

## Ошибки

Валидация JSON/модели — `success=false`, `http_status` 422, `response_json` с `detail`.
Ошибка инференса — `http_status` 500.

## Замечания

- Инференс сериализуется внутри ноды: параллельные `Ask` встают в очередь.
- Native-режим использует модель `ctx320` (`kev-0.8b-w8a8-opt0-ctx320.rkllm`).
- Для native нужны RKLLM 1.3.1 / RKNN 2.3.2 и доступ к `/dev/dri`, `/dev/dma_heap`.