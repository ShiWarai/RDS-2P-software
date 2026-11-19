# YOLO и преследование синего шарика

Одна ONNX-модель `models/yolov8n_balls.onnx` используется браузерным симулятором
и реальным ROS-узлом. Выходные классы: `tree`, `bush`, `rock`, `flower`,
`blue_ball`, `red_ball`, `green_ball`. При выборе цели используется только
YOLO-рамка `blue_ball` с confidence ≥ 0.35; HSV и координаты объектов сцены
в рабочем контуре отсутствуют.

Вход ONNX — **640×480** (`NCHW: 1×3×480×640`), как у RGB-камеры.
Кадр 640×480 поступает в сеть без уменьшения и без полей. Для других размеров
сохраняются пропорции и добавляются поля до прямоугольного входа 640×480.

## Запуск на роботе

Соберите пакет в обычном ROS workspace и установите его Python-зависимости:

```bash
cd ros_packages
python3 -m pip install -c constraints.txt -r src/rds_2p_vision/requirements.txt
colcon build --packages-select rds_2p_vision
source install/setup.bash
```

В отдельных терминалах запустите RGB-камеру, YOLO и rosbridge:

```bash
ros2 launch rds_2p astra_mini_rgb.launch.py
ros2 launch rds_2p_vision ball_follow.launch.py image_topic:=/camera/color/image_raw
ros2 launch rosbridge_server rosbridge_websocket_launch.xml
```

Если rosbridge ещё не установлен: `sudo apt install ros-humble-rosbridge-suite`.
Имя launch-файла приведено в [исходном rosbridge_server](https://github.com/RobotWebTools/rosbridge_suite/blob/ros2/rosbridge_server/launch/rosbridge_websocket_launch.xml).
Для HTTPS-страницы используйте `wss://` с TLS-настройками rosbridge.

Обычный контроллер походки `rds_2p_inference` и `cmd_vel_mux` должны быть
запущены существующим bringup робота. Mux из `rds_2p_joystick` теперь включает
источник `ball_follow` с приоритетом 40, ниже джойстика (100), клавиатуры (90)
и голоса (50). Если mux уже запущен со старой конфигурацией, перезапустите его
с обновлённым `cmd_vel_mux.yaml`. Для отдельного запуска:

```bash
ros2 run rds_2p_joystick cmd_vel_mux.py --ros-args \
  --params-file src/rds_2p_joystick/config/cmd_vel_mux.yaml
```

В веб-интерфейсе справа снизу раскройте **«Реальная панда · ROS 2»**, введите
`ws://IP_РОБОТА:9090`, нажмите **«Подключить робота»**. Надпись кнопки меняется
на **«Робот: следовать за синим»**: она теперь включает ROS-узел, а не походку
симулятора. Отключение соединения возвращает кнопку в режим симулятора.

## Контракт и остановка

- RGB-вход: `sensor_msgs/Image`, по умолчанию `/camera/color/image_raw`.
  Поддерживаются `rgb8`, `bgr8`, `rgba8`, `bgra8`, `mono8`, включая padding строк.
- Разрешение: `/ball_follow/enable`, `std_msgs/Bool`. Узел стартует выключенным.
  Веб-интерфейс посылает heartbeat каждые 200 мс; без него через 700 мс
  преследование выключается. Это не защёлкнутая команда включения.
- Выход: `/cmd_vel/ball_follow`, `geometry_msgs/Twist`; затем mux → `/cmd_vel`
  → существующий inference-контроллер. Масштабирование команды остаётся
  в том же контроллере, что используется ручным управлением.
- Статус: `/ball_follow/status`, `std_msgs/String` с JSON: готовность, enabled,
  рамка цели, время inference, возраст кадра и ошибка.
- Просмотр: `/ball_follow/image/compressed`, JPEG с рамками YOLO; при подключении
  робота вкладка компьютерного зрения показывает этот реальный поток.
- Нет цели, ошибка inference или возраст кадра >700 мс → нулевая скорость.
  Потеря heartbeat → выключение и освобождение источника mux. Команда от
  другого источника mux выключает преследование. Инференс камеры выполняется
  в отдельном потоке и не блокирует таймер остановки 20 Гц.

Пороги, топики и число CPU-потоков задаются в `config/ball_follow.yaml`.
Близость оценивается по относительной ширине рамки (по умолчанию 0.18),
поэтому этот параметр нужно сверить с FOV камеры и размером физического шарика.

## Обучение и предел проверки

Исходный обученный ONNX на четыре класса сохранён в эксперименте. Его веса
восстановлены в PyTorch из fused convolution; перед обучением автоматически
сравниваются выходы исходной и восстановленной сети. Затем добавляются три
класса шариков, а исходные четыре поддерживаются псевдоразметкой учителя.

Набор из 450 кадров получен из RGB-камеры сцены с вариациями ракурса,
расстояния, FOV, освещения, цветов и размеров. Для шариков разметка строится
по видимым маскам объектов; она используется только при подготовке данных.
Разбиение: 360 train / 45 val / 45 test, детерминированные разные seeds.
Модель обучается и экспортируется официальным [Ultralytics workflow](https://docs.ultralytics.com/modes/train/).

Повторение из корня репозитория (сервер эксперимента должен работать):

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r experiments/rds-2p_mujoco_wasm/tools/requirements-vision-train.txt
python experiments/rds-2p_mujoco_wasm/tools/collect_ball_dataset.py --url http://localhost:8085 --count 450
.venv/Scripts/python experiments/rds-2p_mujoco_wasm/tools/train_ball_yolo.py --epochs 35
```

Сборщик кадров по умолчанию использует установленный Chrome в Windows.
Для Linux измените `executable_path` или используйте установленный Playwright Chromium.
Отчёт и SHA-256 весов: `models/training_report.json`; полные обучающие
артефакты и `.pt` checkpoint: `experiments/rds-2p_mujoco_wasm/.test/vision_training/`.
Для продолжения прерванного обучения передайте `--resume .../weights/last.pt`.
Для переэкспорта существующего checkpoint в 640×480 без нового обучения:

```bash
.venv/Scripts/python experiments/rds-2p_mujoco_wasm/tools/export_ball_yolo.py experiments/rds-2p_mujoco_wasm/.test/vision_training/runs/balls_recovered/weights/best.pt
```

Веса переэкспортированы официальным [ONNX export](https://docs.ultralytics.com/integrations/onnx/)
с `imgsz=(480, 640)`. Метрики обучения в отчёте относятся к исходной проверке
при `imgsz=320`; увеличение входа само по себе не подтверждает рост точности.
Для дообучения на размеченных реальных кадрах задайте `--data /path/to/data.yaml`
с теми же семью классами и независимой реальной test-выборкой.

**Обучение и метрики относятся к синтетическим кадрам.** Подключение реальной
камеры и ROS-управления реализовано, но физический робот в этой среде недоступен.
Качество на реальных шариках пока не измерено. Для подтверждения нужны
размеченные кадры именно с его камеры, в используемом освещении, и отдельная
проверка на роботе. Синтетическая точность не доказывает перенос на реальную сцену.
