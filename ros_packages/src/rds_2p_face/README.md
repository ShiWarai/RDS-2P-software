# rds_2p_face

Пакет для визуализации данных тачпада PS4 контроллера и отображения изображений на физическом дисплее ST7789.

## Описание

Пакет содержит четыре ноды:
- **`touchpad_drawer`** - преобразует данные касаний тачпада PS4 контроллера в черно-белое изображение, которое можно использовать для отображения "лица" робота. Нода подписывается на данные тачпада и джойстика, рисует линии и точки на изображении с настраиваемой толщиной кисти, и публикует результат в виде ROS2 изображения.
- **`image_processor`** - обрабатывает изображения из `/face/raw_image`: масштабирует до заданного разрешения и конвертирует в rgb8 формат. Поддерживает любые входные форматы (цветные и ч/б) и разрешения.
- **`display_face`** - отображает изображения из ROS2 топика на физическом дисплее ST7789 (280x240) через SPI интерфейс.
- **`lip_sync_face`** (Python) — липсинк по `AudioStamped`: манифест [config/lip_sync_manifest.json](config/lip_sync_manifest.json) (правила рисунка и уровни `picture_ru`), PNG в `data/lip_sync`.

## Возможности

- 📱 Рисование линий при быстром движении по тачпаду
- ⚫ Рисование точек при медленном движении или одиночных касаниях
- 🎨 Настраиваемая толщина кисти (1-40 пикселей)
- 🧹 Функция стирания изображения
- 🖼️ Публикация изображения в формате `mono8` для просмотра в rviz2

## Зависимости

### ROS2 зависимости
- `rclcpp` - ROS2 C++ клиентская библиотека
- `sensor_msgs` - ROS2 сообщения для изображений и джойстика
- `geometry_msgs` - ROS2 сообщения для геометрических данных
- `cv_bridge` - мост между ROS и OpenCV для работы с изображениями
- `image_transport` - транспорт для изображений в ROS
- `rclpy`, `audio_common_msgs`, `python3-numpy`, `python3-pil` — для ноды **`lip_sync_face`**

### Системные зависимости
- `OpenCV` - библиотека компьютерного зрения (требуется для нод `touchpad_drawer` и `image_processor`)
  ```bash
  sudo apt-get install libopencv-dev
  ```
- `wiringPi` - библиотека для работы с GPIO/SPI (требуется для ноды `display_face`)
  ```bash
  sudo apt-get install wiringpi
  ```

## Ноды

### touchpad_drawer

#### Топики

**Подписки:**
- **`/joy/touchpad`** (`geometry_msgs/msg/PointStamped`)
  - Данные касаний тачпада PS4 контроллера
  - Координаты: x (0-1920), y (0-943)

- **`/joy`** (`sensor_msgs/msg/Joy`)
  - Данные джойстика для управления толщиной кисти и стиранием
  - Используется ось L2 (индекс 4) и кнопка крестика (кнопка 0)

**Публикации:**
- **`/face/raw_image`** (`sensor_msgs/msg/Image`)
  - Черно-белое изображение размером 1920x943 пикселей
  - Формат: `mono8` (8-битное монохромное)
  - Частота публикации: ~30 FPS

### image_processor

#### Топики

**Подписки:**
- **`/face/raw_image`** (`sensor_msgs/msg/Image`)
  - Входное изображение любого разрешения и формата (цветное или ч/б)
  - Поддерживаются форматы: mono8, rgb8, bgr8 и другие

**Публикации:**
- **`/face/image`** (`sensor_msgs/msg/Image`)
  - Обработанное изображение
  - Формат: `rgb8` (цветное RGB)
  - Разрешение: настраивается параметрами (по умолчанию 280x240)

#### Параметры

- **`output_width`** (int, по умолчанию: 280) - ширина выходного изображения в пикселях
- **`output_height`** (int, по умолчанию: 240) - высота выходного изображения в пикселях

#### Функциональность

- Масштабирование изображения до заданного разрешения
- Автоматическая конвертация ч/б изображений в цветные (rgb8)
- Поддержка различных входных форматов (mono8, rgb8, bgr8 и др.)
- Оптимизированная обработка с использованием OpenCV

### display_face

#### Топики

**Подписки:**
- **`/face/image`** (`sensor_msgs/msg/Image`)
  - Входное изображение для отображения на дисплее
  - Формат: `rgb8` (цветное RGB, 3 байта на пиксель)
  - Разрешение: 280x240 пикселей
  - Автоматически преобразуется в RGB565 для отображения на дисплее ST7789

### lip_sync_face

Подписка на **`/audio/output`** (`audio_common_msgs/msg/AudioStamped`), по умолчанию только `header.frame_id` = `tts.paroli` (совместимо с `paroli_ros2`).

Публикация в **`/face/image`** (`sensor_msgs/msg/Image`, rgb8, 280×240 по умолчанию).

Манифест: **`share/rds_2p_face/config/lip_sync_manifest.json`** (поля `_drawing_rules_ru`, `picture_ru` по уровням). PNG: **`share/rds_2p_face/data/lip_sync/`**.

Запуск:

```bash
ros2 launch rds_2p_face lip_sync_face.launch.py
```

Не публикуйте одновременно липсинк и тачпад-пайплайн в один и тот же **`/face/image`** без отдельной ноды-смешивания (см. комментарий в launch).

## Управление

### touchpad_drawer

#### Толщина кисти

Управляется через **ось L2** (5-я ось, индекс 4):
- **L2 = -1** → максимальная толщина (40 пикселей)
- **L2 = 1** → минимальная толщина (1 пиксель)
- Размер кисти сохраняется для каждой точки касания, поэтому изменение L2 не влияет на уже нарисованные линии

#### Стирание

Для стирания изображения:
1. Нажмите **L2 до упора** (значение < -0.9)
2. Удерживая L2, нажмите **кнопку крестика** (кнопка 0)

Защита от повторного срабатывания: минимум 0.3 секунды между очистками.

### image_processor

Нода обрабатывает изображения из `/face/raw_image`: масштабирует до заданного разрешения и конвертирует в rgb8 формат. Поддерживает любые входные форматы и разрешения.

### display_face

Нода автоматически инициализирует дисплей ST7789 при запуске и отображает каждое новое изображение, полученное из топика `/face/image`. Дисплей настраивается с разрешением 280x240 пикселей и использует RGB565 формат (16 бит на пиксель).

## Установка и сборка

```bash
cd ~/RDS-2P-software/ros_packages
colcon build --packages-select rds_2p_face
source install/setup.bash
```

## Запуск

### touchpad_drawer

#### Через launch файл (рекомендуется)

```bash
ros2 launch rds_2p_face touchpad_drawer.launch.py
```

С указанием уровня логирования:

```bash
ros2 launch rds_2p_face touchpad_drawer.launch.py log_level:=debug
```

#### Прямой запуск ноды

```bash
ros2 run rds_2p_face touchpad_drawer
```

### image_processor

#### Через launch файл (рекомендуется)

```bash
ros2 launch rds_2p_face image_processor.launch.py
```

С настройкой разрешения выходного изображения:

```bash
ros2 launch rds_2p_face image_processor.launch.py output_width:=320 output_height:=240
```

С указанием уровня логирования:

```bash
ros2 launch rds_2p_face image_processor.launch.py log_level:=debug
```

#### Прямой запуск ноды

```bash
ros2 run rds_2p_face image_processor
```

С параметрами через ROS:

```bash
ros2 run rds_2p_face image_processor --ros-args -p output_width:=320 -p output_height:=240
```

### display_face

**ВАЖНО:** Для работы ноды `display_face` требуется доступ к GPIO/SPI через `/dev/mem`, что требует прав root.

#### Через скрипт-обёртку (рекомендуется)

Самый простой способ - использовать скрипт-обёртку:

```bash
cd ~/RDS-2P-software/ros_packages
source install/setup.bash
./install/rds_2p_face/lib/rds_2p_face/display_face_sudo.sh
```

С указанием уровня логирования:

```bash
cd ~/RDS-2P-software/ros_packages
source install/setup.bash
./install/rds_2p_face/lib/rds_2p_face/display_face_sudo.sh log_level:=debug
```

Или напрямую из исходников:

```bash
cd ~/RDS-2P-software/ros_packages/src/rds_2p_face/scripts
./display_face_sudo.sh
```

#### Через launch файл с sudo

```bash
sudo -E env PATH="$PATH" ros2 launch rds_2p_face display_face.launch.py
```

С указанием уровня логирования:

```bash
sudo -E env PATH="$PATH" ros2 launch rds_2p_face display_face.launch.py log_level:=debug
```

#### Прямой запуск ноды

```bash
sudo -E ros2 run rds_2p_face display_face
```

**Требования:**
- Установлена библиотека `wiringPi`
- Запуск с правами root (через sudo) из-за доступа к `/dev/mem`
- Дисплей ST7789 правильно подключен к Orange Pi (пины: RES=5, DC=7, CS=18, SPI channel 4)

## Просмотр в rviz2

1. Запустите rviz2:
   ```bash
   rviz2
   ```

2. Добавьте визуализацию изображения:
   - Нажмите **Add** → **By topic** → `/face/raw_image` → **Image** → **OK**
   
   Или вручную:
   - Нажмите **Add** → **Image**
   - В поле **Image Topic** выберите `/face/raw_image`
   - **Fixed Frame** можно оставить по умолчанию или установить `touchpad`

3. Изображение должно отображаться в окне rviz2.

## Технические детали

### touchpad_drawer

#### Алгоритм рисования

- **Быстрое касание** (время между точками < 0.4 сек): рисуется линия между точками
- **Медленное касание** (время между точками ≥ 0.4 сек): рисуется отдельная точка
- Используется OpenCV для оптимизированной отрисовки (cv::line, cv::circle)
- Точки и линии рисуются с настраиваемой толщиной кисти

#### Параметры

- **Разрешение изображения**: 1920x943 пикселей (соответствует разрешению тачпада PS4)
- **Максимальная история точек**: 500 точек
- **Диапазон толщины кисти**: 10-100 пикселей (радиус)
- **Порог быстрого касания**: 0.4 секунды (FAST_TOUCH_THRESHOLD)
- **Частота публикации**: ~30 FPS (33 мс)
- **Лимит точек за кадр**: 50 точек (предотвращает зависания)

#### Производительность

- Использование OpenCV для отрисовки (ускорение в 10-100 раз)
- Atomic переменные для быстрого доступа к brush_size без блокировок
- std::deque для эффективного управления историей точек
- Лимит обработки точек за кадр для предотвращения зависаний
- Автоматическое удаление старых точек (старше 5 секунд)
- Флаг dirty для пропуска пустых публикаций

### display_face

#### Параметры дисплея

- **Тип дисплея**: ST7789 (TFT LCD контроллер)
- **Разрешение**: 280x240 пикселей
- **Формат цвета**: RGB565 (16 бит на пиксель)
- **Интерфейс**: SPI (Serial Peripheral Interface)
- **Скорость SPI**: 20 MHz

#### Параметры подключения (WiringPi пины)

- **RES (Reset)**: GPIO 5
- **DC (Data/Command)**: GPIO 7
- **CS (Chip Select)**: GPIO 18
- **SPI Channel**: 4
- **SPI Port**: 0

#### Технические особенности

- Автоматическая инициализация дисплея при запуске ноды
- Преобразование RGB8 (24 бита) → RGB565 (16 бит) для оптимизации передачи данных
- Отправка данных блоками по 4096 байт для эффективной работы SPI
- Проверка формата и разрешения входящих изображений с предупреждениями

#### Ограничения

- Поддерживается только формат `rgb8` (цветное RGB, 3 байта на пиксель)
- Разрешение изображения должно быть строго 280x240 пикселей
- Для работы требуется доступ к GPIO/SPI (обычно требует запуск от root)

## Требования

### Для touchpad_drawer

Необходимо, чтобы были запущены:
- Нода публикации данных тачпада (например, `ps4_touchpad_node` из пакета `rds_2p_joystick`)
- Нода публикации данных джойстика (например, `joy_node`)

### Для display_face

- Библиотека `wiringPi` установлена в системе
- Дисплей ST7789 подключен к Raspberry Pi
- Права доступа к GPIO/SPI (обычно требует запуска от root)

## Примеры использования

### Пример 1: Визуализация тачпада в rviz2

```bash
# Терминал 1: Джойстик и тачпад
ros2 launch rds_2p_joystick ps4_joystick.launch.py

# Терминал 2: Визуализация тачпада
ros2 launch rds_2p_face touchpad_drawer.launch.py

# Терминал 3: rviz2
rviz2
```

### Пример 2: Отображение изображений на физическом дисплее

```bash
# Терминал 1: Публикация изображений в /face/image (например, из другого пакета)
ros2 run ваш_пакет publisher_node

# Терминал 2: Отображение на дисплее (требует sudo)
cd ~/RDS-2P-software/ros_packages
source install/setup.bash
./install/rds_2p_face/lib/rds_2p_face/display_face_sudo.sh
```

### Пример 3: Полная система с тачпадом (рекомендуется)

```bash
# Запуск всей системы одной командой
ros2 launch rds_2p_face face_with_touchpad.launch.py
```

С настройкой разрешения выходного изображения:

```bash
ros2 launch rds_2p_face face_with_touchpad.launch.py output_width:=320 output_height:=240
```

### Пример 4: Комбинированное использование (пошагово)

```bash
# Терминал 1: Джойстик и тачпад
ros2 launch rds_2p_joystick ps4_joystick.launch.py

# Терминал 2: Визуализация тачпада (публикует в /face/raw_image)
ros2 launch rds_2p_face touchpad_drawer.launch.py

# Терминал 3: Обработчик изображений (преобразует /face/raw_image в /face/image)
ros2 launch rds_2p_face image_processor.launch.py

# Терминал 4: Отображение на физическом дисплее (требует sudo)
cd ~/RDS-2P-software/ros_packages
source install/setup.bash
./install/rds_2p_face/lib/rds_2p_face/display_face_sudo.sh
```

## Тестирование

### Тестирование display_face

Для тестирования ноды `display_face` можно использовать скрипт `publish_image.py`, который публикует изображение в топик `/face/image`:

```bash
# После сборки пакета
ros2 run rds_2p_face publish_image.py /home/orangepi/face/image/smile3.png
```

Или напрямую из исходников:

```bash
cd ~/RDS-2P-software/ros_packages/src/rds_2p_face
python3 scripts/publish_image.py /home/orangepi/face/image/smile3.png
```

Скрипт автоматически:
- Загружает изображение (поддерживаются форматы: PNG, JPEG, BMP и др.)
- Конвертирует в RGB формат если нужно
- Изменяет размер до 280x240 пикселей если необходимо
- Публикует в топик `/face/image` в формате rgb8

**Требования для скрипта:**
- Python 3
- Pillow (PIL): `pip install Pillow` или `sudo apt-get install python3-pil`

## Структура пакета

```
rds_2p_face/
├── CMakeLists.txt
├── package.xml
├── README.md
├── include/
│   └── rds_2p_face/
│       ├── touchpad_drawer.hpp
│       └── display_face.hpp
├── src/
│   ├── touchpad_drawer.cpp
│   ├── image_processor.cpp
│   └── display_face.cpp
├── include/
│   └── rds_2p_face/
│       ├── touchpad_drawer.hpp
│       ├── image_processor.hpp
│       └── display_face.hpp
├── scripts/
│   └── publish_image.py
└── launch/
    ├── touchpad_drawer.launch.py
    ├── image_processor.launch.py
    ├── face_with_touchpad.launch.py
    └── display_face.launch.py
```

## Автор

Zhuravliov Pavel (zhuravliov.pav@yandex.ru)

## Лицензия

MIT License

