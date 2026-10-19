# Патчи Orbbec (`orbbec_camera`)

**`astra_mini.launch.py`** — в upstream [OrbbecSDK_ROS2](https://github.com/orbbec/OrbbecSDK_ROS2) нет этого launch-файла; скрипт `build_for_robot.sh` после подготовки `src/OrbbecSDK_ROS2` копирует его в `orbbec_camera/launch/` (на роботе).

Меняйте launch здесь и снова запускайте сборку, чтобы обновить дерево `src/`.
