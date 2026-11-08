# Модели

## Что реально использует нода (дефолт)

| Путь | Назначение |
|------|------------|
| `ruslan/encoder.onnx` | энкодер ONNX |
| `ruslan/decoder.rknn` | декодер на NPU |
| `ruslan/ru_RU-ruslan-medium.onnx.json` | конфиг голоса (`espeak: ru`) |
| `espeak-ng-data/` | фонемизация для Piper |

Другие файлы из каталога **`ruslan/`** в paroli (например **`decoder.onnx`**, **`ru_RU-ruslan-medium.onnx`**) нужны для чисто-ONNX декодера — **текущая обвязка их не подключает**, после полного `rsync` их можно удалить, чтобы сэкономить ~100 MiB.

Корень **`models/`** нода не использует: не кладите туда дубликаты `encoder`/`decoder`/`config.json` — только **`ruslan/`** и **`espeak-ng-data/`**.

## Копирование

```bash
# из корня репозитория ros_packages:
rsync -a ~/paroli-tts/models/ruslan/           src/paroli_ros2/models/ruslan/
rsync -a ~/paroli-tts/models/espeak-ng-data/   src/paroli_ros2/models/espeak-ng-data/
# опционально — убрать лишнее после rsync:
rm -f src/paroli_ros2/models/ruslan/decoder.onnx \
      src/paroli_ros2/models/ruslan/ru_RU-ruslan-medium.onnx

colcon build --packages-select paroli_ros2
```

Если при **`--symlink-install`** CMake ругается **`File exists`** / **`Could not create symlink`** по **`espeak-ng-data`**, сначала **`rm -rf install/paroli_ros2/share/paroli_ros2/models`**, затем снова **`colcon build`**.
