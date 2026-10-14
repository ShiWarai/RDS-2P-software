# Docker-образы RDS-2P

Два самодостаточных образа на базе `ros:humble-ros-base`: весь ROS2-стек RDS-2P живёт внутри контейнера, на хостах ROS2 не нужен.

| Образ | Арх | Сборка | Запуск | Назначение |
|---|---|---|---|---|
| `rds2p/robot:humble` | arm64 | `docker/build_robot.sh` **на роботе** | `docker/run_robot.sh` | всё железо робота |
| `rds2p/desktop:humble` | amd64 | `docker/build_desktop.sh` (WSL) | `docker/run_desktop.sh` | twin-симуляция MuJoCo GUI |

Контекст сборки — корень репозитория. `.dockerignore` лежит в `docker/` (build-скрипты копируют его в корень на время сборки).

## Desktop (WSL2 + WSLg)

### Подготовка хоста (один раз)
```bash
sudo apt-get install -y docker.io
sudo usermod -aG docker $USER   # перезапустить сессию
docker info                     # daemon должен отвечать
```
Если проксированная сеть — drop-in для daemon'а (pull образов/пакетов из контейнера идёт через него):
```bash
sudo mkdir -p /etc/systemd/system/docker.service.d
sudo tee /etc/systemd/system/docker.service.d/http-proxy.conf >/dev/null <<'EOF'
[Service]
Environment="HTTP_PROXY=http://10.192.32.118:8080"
Environment="HTTPS_PROXY=http://10.192.32.118:8080"
Environment="NO_PROXY=localhost,127.0.0.1"
EOF
sudo systemctl daemon-reload && sudo systemctl restart docker
```
При корпоративном MITM — добавить CA сервиса в образ или в `/etc/docker/certs.d`.

### Сборка и запуск
```bash
docker/build_desktop.sh    # чинит контекст (vendored subset + obj-меши из urdf_src, vosk-модель) + docker build
docker/run_desktop.sh      # окно MuJoCo через WSLg (DISPLAY/Wayland монтируются)
```
Переменные: `IMAGE=...` (тег), `LAUNCH_OVERRIDE="ros2 launch ..."` (любая команда вместо CMD).

### Проверка (live-верификация twin)
1. **Импорт playground внутри образа:**
   ```bash
   docker run --rm rds2p/desktop:humble "python3 -c 'import mujoco, mujoco_playground; print(\"deps OK\", mujoco.__version__)'"
   ```
2. **GUI + темп joint_states** (в двух терминалах):
   ```bash
   docker/run_desktop.sh                       # окно MuJoCo видно через WSLg
   docker exec <ctn> bash -c 'source /opt/rds2p/install/setup.bash; timeout 10 ros2 topic hz /joint_states'
   ```
   Подтверждено: 50 Hz, 12 суставов.
3. **Хождение** (политика ходит не по `/cmd_vel` напрямую — её выполняет `inference_node`: cmd_vel → ONNX-политика → `/joint_commands` → twin):
   ```bash
   # в twin-контейнере:
   docker exec -d <ctn> bash -c 'for d in /opt/rds2p/install/*/lib; do export LD_LIBRARY_PATH=$LD_LIBRARY_PATH:$d; done; source /opt/rds2p/install/setup.bash; exec ros2 launch rds_2p_inference inference_node.launch.py'
   # затем publisher /cmd_vel linear.x=0.25 на ~6 c — суставы дают циклическую походку (hip до ~0.18 рад)
   ```
   (Через штатный entrypoint `docker run rds2p/desktop:humble "ros2 launch ..."` LD уже проставлен, exec-обёртку выше повторять не нужно.)

### Отладка
- Нет окна / X-ошибка: проверить `echo $DISPLAY` в WSL (WSLg даёт `:0`), на хосте Windows `xhost +local:` не нужен в WSLg по умолчанию; для Wayland — `WAYLAND_DISPLAY=wayland-0`.
- `libsoxr.so.0 not found` при импорте playground — в образе должен стоять `libsoxr0` (пересобрать).
- ROS-CLI на хосте не обязателен: `docker exec -it <ctn> bash` даёт готовый окруженный shell (entrypoint source'ит `/opt/ros/humble` и `/opt/rds2p/install`).
- DDS: контейнер в `--network host`. Run-скрипты фиксуют дефолты проекта: `ROS_DOMAIN_ID=2` (как в `~/.bashrc` рабочих машин) и `RMW_IMPLEMENTATION=rmw_fastrtps_cpp` (в образах cyclone не ставим; оба стенда — Fast DDS, discovery по Wi-Fi между ними проверен). Переопределяются одноимёнными env. Сетевой xml-профиль: `DDS_PROFILES_FILE=/path/to.xml ./docker/run_robot.sh` — монтируется в контейнер и подключается к активному rmw: `FASTRTPS_DEFAULT_PROFILES_FILE` для fastdds-`<profiles>` (пример: `learning/export_inference/configs/fastdds_network.xml`) или `CYCLONEDDS_URI=file://` для cyclone-`<CycloneDDS>` (пример: `configs/cyclonedds_network.xml`).

## Robot (arm64)

Любая arm64-платформа; NPU-ноды (rkllm/rknn, `/dev/rga`, `/dev/mpp_service`) рассчитаны на **RK3588**. Образ собирается **нативно на роботе** — там же и vendor RK-рантайм, и железо. ROS2 на хосте не нужен (jammy-контейнер самодостаточен, версия хост-Ubuntu любая).

### Предварительно на роботе
1. Docker: `sudo apt-get install -y docker.io && sudo usermod -aG docker $USER` (перелогин).
2. `git pull` в `RDS-2P-software`.
3. Vendor RK: положить в `ros_packages/src/rkllm_ros2/vendor/`
   `lib/librkllmrt.so`, `lib/librknnrt.so`, `include/rkllm.h`, `include/rknn_api.h`
   (см. `ros_packages/src/rkllm_ros2/vendor/README.md`). Без них образ соберётся **без rkllm_ros2** (LLM-экшенов не будет), сборка не упадёт.
4. Модели (не в git) — в каталог, который смонтируется в `/models`:
   `.rkllm`/`.rknn` для rkllm, onnx-политика уже в образе (`rds_2p_inference`).

### Сборка
```bash
docker/build_robot.sh
```
Скрипт: проверяет aarch64 и docker; предупреждает о неполном vendor; докачивает отсутствующие клоны (FTServoLibrary, mpu6500, OrbbecSDK_ROS2, audio_common, vosk_ros2 + модель Vosk); затем `docker build`. `ros-humble-orbbec-camera` ставится из apt, если доступен для arm64; если нет — илиbbec-нода добирается сборкой из исходников (с предупреждением при неудаче), сообщения — всегда из workspace-клона.

### Запуск
```bash
MODELS_DIR=$HOME/RDS-2P-models docker/run_robot.sh
# rkllm (имена файлов внутри MODELS_DIR):
RKLLM_MODEL=qwen3-vl.rkllm RKNN_ENCODER_MODEL=encoder.rknn \
LAUNCH_OVERRIDE="ros2 launch rkllm_ros2 rkllm.launch.py llm_model_path:=/models/qwen3-vl.rkllm encoder_model_path:=/models/encoder.rknn" \
docker/run_robot.sh
```
`--privileged --network host --shm-size=4g --group-add audio` — сознательно (разработка): разом открывает `ttyS7`, SocketCAN, NPU (`/dev/rga`, `/dev/dri`, `/dev/mpp_service`), SPI/GPIO дисплея, `/dev/snd`, USB-камеры. Точечные `--device/--cap-add` — закомментированный блок в `run_robot.sh` для будущего харденинга.

### Чек-лист железа в контейнере
```bash
LAUNCH="bash" docker/run_robot.sh
# ros2 topic list / ros2 node list
ros2 topic hz /joint_states            # моторы через /dev/ttyS7 (ftservo в is_sim=false)
ros2 topic pub -r 10 geometry_msgs/msg/Twist '{linear: {x: 0.1}}' /cmd_vel   # ходьба (через inference_node: cmd_vel→ONNX→joint_commands)
# в том же контейнере отдельным запуском:
ros2 launch rds_2p_inference inference_node.launch.py
aplay -l                               # /dev/snd виден
# дисплей-морда:
ros2 launch rds_2p display.launch.py
# голос:
ros2 launch rds_2p voice_system.launch.py
# камера Astra Mini (если orbbec в образе):
ros2 launch rds_2p astra_mini.launch.py
```
По умолчанию стартует `rds_2p_complete.launch.py` (моторы + bridges joints<->motors).

## Известные грабли
- `libonnxruntime.so.1`: CMake пакета ставит в install только `libonnxruntime.so` и `.so.1.19.2`, а бинарь линкуется на SONAME `.so.1` — Dockerfile досоздаёт этот симлинк (слои `ln -sf` после colcon). При нативной сборке на хосте это тоже актуально.
- ROS-CLI хоста в WSL может не видеть топики контейнера (DDS multicast через WSL NAT) — отлаживай внутри: `docker exec <ctn> bash -c 'source /opt/rds2p/install/setup.bash; ros2 topic list'`.
- Ходьба = `inference_node` (cmd_vel→ONNX→joint_commands) + twin; один `run_desktop.sh` даёт стоящего и дышащего симом робота.
- `arm64` apt может не иметь `ros-humble-orbbec-camera` — сборка robot это переживает (см. выше).
- `rkllm` хочет большой `/dev/shm` — 4g в `run_robot.sh`, не уменьшать.
- NumPy 2.x и cv_bridge Humble: образы пинят `numpy<2` в pip — не ослаблять.
- udev-правила ds4drv из `build_for_robot.sh` внутрь образа не переносятся: при `--privileged` hidraw/uinput доступны всем; для точечных прав правила создавать на хосте.
- Хостам робота/desktop ROS2 не нужен; сборочные скрипты хоста (`ros_packages/scripts/build_for_*`) остаются для нативной разработки — docker-путь от них независим.
