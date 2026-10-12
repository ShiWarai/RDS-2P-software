# rkllm_ros2

ROS 2 (Humble): **RKNN vision encoder** + **RKLLM**, один унифицированный Action в стиле **chat completion** (текст обязателен, картинка опциональна), стриминг в фидбеке и топиках.

## Зависимости

- Системные: OpenCV (`cv_bridge`), `sensor_msgs`, `rclcpp`, `rclcpp_action`.
- **Vendor:** см. [vendor/README.md](vendor/README.md).

Модели **`.rknn` / `.rkllm`** не в git — пути через параметры launch.

## Как пользоваться (минимальный пример)

1. Сборка и окружение (один раз за сессию):

   ```bash
   cd ~/RDS-2P-simulator/ros_packages
   source /opt/ros/humble/setup.bash
   source install/setup.bash
   ```

2. **Терминал A** — поднять модель:

   ```bash
   ros2 launch rkllm_ros2 rkllm.launch.py \
     encoder_model_path:=/home/orangepi/models/qwen3-vl-2b-instruct_vision_640_rk3588.rknn \
     llm_model_path:=/home/orangepi/models/qwen3-vl-2b-instruct_w8a8_rk3588.rkllm
   ```

3. **Терминал B** — полный набор команд в разделе **Примеры вызова** ниже (`scripts/`).

Быстрый smoke-тест после шага 2:

```bash
ros2 run rkllm_ros2 example_chat.py
```

```bash
ros2 run rkllm_ros2 example_vision.py "Что видишь? Ответь кратко."
```

Нужны запущенная камера (или корректный топик `sensor_msgs/Image`) и путь к кадру в правильной кодировке — см. примеры с **`--topic`** и **`--image`** ниже.

### Смотреть поток токенов в ROS (пока идёт генерация)

В отдельном терминале:

```bash
ros2 topic echo /rkllm_ros2/text_chunks
# после успешного goal полный текст также в:
ros2 topic echo /rkllm_ros2/text --once
```

### Что вызывается под капотом

- Action-сервер: **`/rkllm_ros2/complete`**, тип **`rkllm_ros2_msgs/action/ChatCompletion`**.
- В goal всегда нужен **`user_message`**; поле **`image`** можно не заполнять (только текст) или заполнить для VLM.

Дальше — таблица интерфейсов и **примеры `ros2 run`** для `scripts/`.

## Интерфейсы

| Интерфейс | Тип | Описание |
|-----------|-----|----------|
| `~/complete` | `rkllm_ros2_msgs/action/ChatCompletion` | **Goal:** `user_message` (перед infer санитизируется: trim и снятие ведущих префиксов `user:` / `robot:`); **`image`** опционально (multimodal: к промпту добавляется `<image>`). **`keep_history`**: при **`persist_session_kv:=true`** на ноде поле **не управляет** накоплением KV в RKLLM (infer всегда с «памятью»); сброс только **`~/clear_kv_cache`**. При **`persist_session_kv:=false`** — прежняя семантика: очистка KV и флаг infer берутся из goal. `max_new_tokens` в goal не подменяет лимит init-time. Фидбек/result — поток и итоговый текст + метрики. |
| `~/clear_kv_cache` | `std_srvs/Trigger` | Сброс KV на стороне RKLLM (простой диалог без наследия контекста прошлого клиента). Отказ, если нода занята goal. |
| `~/text_chunks` | `std_msgs/String` | Чанки генерации |
| `~/text` | `std_msgs/String` | Полный ответ после успешного goal |

Полноценный OpenAI-массив `messages[]` в ROS 2 потребовал бы своих `.msg`; здесь **один user-turn за goal**. Клиент **`example_chat.py`** по умолчанию шлёт **одну реплику за раз** с **`keep_history=true`** (согласовано с **`persist_session_kv:=true`** на ноде). Режим **`--replay`** восстанавливает повтор всего диалога в **`user_message`** и **`keep_history=false`** — совместим с **`persist_session_kv:=false`**.

Параметры **`top_k`**, **`top_p`**, **`temperature`**, **`repeat_penalty`** (и при необходимости **`frequency_penalty`**, **`presence_penalty`**) задаются как у **`RKLLMParam`** и применяются в **`rkllm_init`**. Дефолты launch/ноды выровнены под **`generation_config.json`** веса **Qwen3-VL-2B-Instruct** на Hugging Face (`top_k=20`, `top_p=0.8`, `temperature=0.7`, `repeat_penalty=1.0`; на плате после квантования может понадобиться подстройка). **`persist_session_kv`** (по умолчанию **true**): режим как в demo — **`RKLLMInferParam.keep_history = 1`** всегда, из обработчика goal не вызывается **`rkllm_clear_kv_cache`** в зависимости от goal; сброс только сервисом **`~/clear_kv_cache`**. Значение **`false`** — legacy: **`keep_history`** и очистка KV по полю goal.

Параметр **`apply_chat_template`** (по умолчанию **false**): при **true** вызывается **`rkllm_set_chat_template`**, что по предупреждению RKLLM **отключает встроенный разбор шаблона** из экспортированной модели (`enable_thinking` и т.д.). Для **Qwen3-VL**, собранной по [multimodal_model_demo](https://github.com/airockchip/rknn-llm/tree/main/examples/multimodal_model_demo), C++ `main.cpp` держит этот вызов **закомментированным** и опирается на авто-шаблон; включайте ручной шаблон только осознанно (см. обсуждения вроде [#377](https://github.com/airockchip/rknn-llm/issues/377)). Системная роль в шаблоне задаётся параметром **`chat_template_system`** (в **`rkllm.launch.py`** — аргумент **`system_prompt`**); на модель это влияет только при **`apply_chat_template:=true`**. Пустой **`system_prompt`** оставляет встроенный текст по умолчанию ноды.

Параметр **`clear_kv_after_idle_sec`** (по умолчанию **0**): если **> 0**, после **каждого завершённого** goal таймер отсчитывает простой; пока нода не занята новым goal и прошло больше **N** секунд с момента последнего завершения, вызывается **`rkllm_clear_kv_cache`** (как сервис **`~/clear_kv_cache`**). Тик проверки — **5 с**. **0** — авто-сброс отключён.

**Замечание:** `goal.max_new_tokens != 0` не заменяет лимит при `rkllm_init` — см. параметры ноды.

**Одиночный запрос без «хвоста» контекста:** при **`persist_session_kv:=true`** вызовите **`~/clear_kv_cache`** перед goal (**`example_chat.py`** / **`example_vision.py`** делают это при старте по умолчанию, если не **`--no-clear-start`**) или временно запустите ноду с **`persist_session_kv:=false`**.

## Сборка

```bash
cd ~/RDS-2P-simulator/ros_packages
source /opt/ros/humble/setup.bash
colcon build --packages-select rkllm_ros2
source install/setup.bash
```

При ошибке symlink для Python-интерфейсов:

```bash
rm -rf build/rkllm_ros2 install/rkllm_ros2
colcon build --packages-select rkllm_ros2 --symlink-install
```

## Запуск

```bash
ros2 launch rkllm_ros2 rkllm.launch.py \
  encoder_model_path:=/home/orangepi/models/qwen3-vl-2b_vision_rk3588.rknn \
  llm_model_path:=/home/orangepi/models/qwen3-vl-2b-instruct_w8a8_rk3588.rkllm
```

Сэмплинг (**`top_k`**, **`top_p`**, **`temperature`**, **`repeat_penalty`**) и **`persist_session_kv`** уже имеют дефолты как выше; при необходимости переопределяйте в команде. Пример с ручным system и шаблоном:

```bash
ros2 launch rkllm_ros2 rkllm.launch.py \
  encoder_model_path:=/path/to/vision.rknn \
  llm_model_path:=/path/to/model.rkllm \
  system_prompt:='Всегда говори и помни, что ты робот-панда. Отвечай кратко.' \
  apply_chat_template:=true
```

Дополнительно в launch: **`frequency_penalty`**, **`presence_penalty`** (по умолчанию `0.0`), **`clear_kv_after_idle_sec`** (0 = без авто-сброса KV), **`apply_chat_template`**, **`system_prompt`** (пусто = дефолт **`chat_template_system`**, актуально при **`apply_chat_template:=true`**).

Нода: **`rkllm_ros2`**, Action: **`/rkllm_ros2/complete`**.

Пошаговые сценарии см. раздел **«Как пользоваться»** в начале README.

## Просмотр интерфейса

```bash
ros2 interface show rkllm_ros2_msgs/action/ChatCompletion
```

## Примеры вызова

Исполняемые скрипты лежат в репозитории в [`scripts/`](scripts/); после `colcon build` и `source install/setup.bash` — **`ros2 run rkllm_ros2 example_chat.py`** и **`example_vision.py`**. Свой узел можно собирать по тому же контракту Action (поля goal — см. команду **`ros2 interface show`** выше).

Для текстового клиента см. также [`scripts/example_chat.py`](scripts/example_chat.py), для multimodal без `cv_bridge` — [`scripts/example_vision.py`](scripts/example_vision.py).

### Текст: `example_chat.py`

Интерактив: одна строка stdin = один промпт в модель (выход: `exit` / `quit` / Ctrl+D). При старте по умолчанию вызывается **`~/clear_kv_cache`**, чтобы не тащить контекст от прошлых клиентов.

```bash
ros2 run rkllm_ros2 example_chat.py
```

Один запрос из argv и выход:

```bash
ros2 run rkllm_ros2 example_chat.py "Переведи на английский: добрый день"
```

Не сбрасывать KV при запуске клиента (продолжить уже накопленный на ноде контекст):

```bash
ros2 run rkllm_ros2 example_chat.py --no-clear-start
```

Каждый goal изолированно: перед отправкой **`~/clear_kv_cache`**, в goal — **`keep_history=false`** (удобно при **`persist_session_kv:=true`**, когда нужен «каждый раз с чистого листа»):

```bash
ros2 run rkllm_ros2 example_chat.py --no-history "Один изолированный вопрос"
```

```bash
ros2 run rkllm_ros2 example_chat.py --no-history
```

Legacy: полный диалог кладётся в текст одного **`user_message`**, **`keep_history=false`**. Осмысленно вместе с **`persist_session_kv:=false`** на ноде; иначе при **`persist_session_kv:=true`** контекст дублируется (KV + длинный prompt):

```bash
ros2 run rkllm_ros2 example_chat.py --replay
```

Другой action (другой namespace / имя сервера):

```bash
ros2 run rkllm_ros2 example_chat.py --action /my_namespace/complete "привет"
```

### Картинка: `example_vision.py`

Кадр с топика по умолчанию **`/camera/color/image_raw`** (`sensor_msgs/Image`, rgb8 или bgr8):

```bash
ros2 run rkllm_ros2 example_vision.py "Что ты видишь? Ответь кратко."
```

Свой топик и ожидание первого кадра до 25 с:

```bash
ros2 run rkllm_ros2 example_vision.py \
  --topic /orbbec/camera/color/image_raw \
  --timeout 25 \
  "Есть ли люди в кадре?"
```

Файл jpg/png (нужен **`python3-pil`** / Pillow):

```bash
ros2 run rkllm_ros2 example_vision.py --image /path/to/photo.jpg "Опиши сцену кратко"
```

Без сброса KV перед запросом и с накоплением на стороне RKLLM между вызовами (**`--keep-history`**):

```bash
ros2 run rkllm_ros2 example_vision.py --no-clear-start --keep-history \
  --image ./frame_a.jpg "Что на изображении?"
```

Меньше промежуточных логов:

```bash
ros2 run rkllm_ros2 example_vision.py --quiet --topic /camera/color/image_raw "Кратко: что в кадре?"
```

Свой action:

```bash
ros2 run rkllm_ros2 example_vision.py --action /rkllm_ros2/complete --image ./x.png "?"
```

Собственный узел с **`cv_bridge`** по-прежнему возможен при **`numpy<2`**; **`rkllm_node`** принимает multimodal из любого клиента по Action.

## Контекст и грабли

- **`persist_session_kv` / KV:** при **`persist_session_kv:=true`** (по умолчанию) RKLLM ведёт себя как локальный demo: между goals контекст сохраняется, **`goal.keep_history`** не отключает накопление KV; для «чистого» one-shot вызовите **`~/clear_kv_cache`** перед запросом или используйте **`persist_session_kv:=false`**. При **`persist_session_kv:=false`** — прежняя семантика: при **`keep_history=false`** нода вызывает **`rkllm_clear_kv_cache`** перед генерацией. Опционально **`clear_kv_after_idle_sec` > 0** в launch сбрасывает KV после тишины; **0** — только ручной **`~/clear_kv_cache`**.
- **`example_chat.py`:** по умолчанию без **`--replay`** не дублируйте историю в тексте промпта — иначе при **`persist_session_kv:=true`** контекст задваивается (KV + полный диалог в prompt). Режим **`--replay`** рассчитан на **`persist_session_kv:=false`**.
- **`cv_bridge` / NumPy 2:** сборки ROS Humble часто под NumPy 1.x; при **NumPy ≥ 2** импорт `cv_bridge` может падать (`_ARRAY_API`). Обход: **`example_vision.py`** (топик или файл без `cv_bridge`), venv с **`numpy<2`**, или временно только **`example_chat.py`**.
- **`rkllm_set_chat_template`:** вызов **перекрывает** авто-шаблон из `.rkllm`; для типичного **Qwen3-VL** после конвертации rknn-llm часто держат **`apply_chat_template:=false`** (как в upstream `multimodal_model_demo/deploy/src/main.cpp`). Если в логах RKLLM — предупреждение про отключение парсинга шаблона — это как раз оно; странные ответы часто из‑за несовпадения ручного шаблона с VL/Qwen3 (issues [#377](https://github.com/airockchip/rknn-llm/issues/377), [#429](https://github.com/airockchip/rknn-llm/issues/429)).
- Неверный **`RUNPATH`** / старый **`LD_LIBRARY_PATH`**: см. [vendor/README.md](vendor/README.md); launch префиксует путь к `vendor/lib`.
- **Версия runtime < toolkit** в `.rkllm` — обновите `librkllmrt.so`.
- **`img_start` / `img_end` / `img_content`** подбираются под семейство модели.
- Один активный goal; второй будет **отклонён**.

## Лицензии

- `src/image_enc.cc` / `image_enc.h` — Rockchip `rknn-llm` (шапка файлов).
- Остальное — Apache-2.0 (`package.xml`).
