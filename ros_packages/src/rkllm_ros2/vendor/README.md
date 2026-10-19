# vendor/ — RK-рантайм для rkllm_ros2

Бинарники и заголовки Rockchip здесь **не в git** (см. `.gitignore`), кладутся локально/на роботе.
CMake без них падает с `FATAL_ERROR` (см. `CMakeLists.txt`).

## Что нужно

| Файл | Откуда |
|------|--------|
| `lib/librkllmrt.so` | `rknn-llm/rkllm-runtime/Linux/librkllm_api/aarch64/librkllmrt.so` |
| `include/rkllm.h` | `rknn-llm/rkllm-runtime/Linux/librkllm_api/include/rkllm.h` |
| `lib/librknnrt.so` | `rknn-llm/examples/multimodal_model_demo/deploy/3rdparty/librknnrt/Linux/librknn_api/aarch64/librknnrt.so` |
| `include/rknn_api.h` | `…/librknnrt/Linux/librknn_api/include/rknn_api.h` |

`src/image_enc.cc` / `image_enc.h` в пакете — копии `multimodal_model_demo/deploy/src/`
(лицензия Rockchip, шапка файлов). При обновлении demo сверьте их diff'ом.

## Текущие версии (2026-10)

- **RKLLM runtime 1.3.1** (`release-v1.3.1`, commit `f739053`) — `rkllm_init` принимает
  `RKLLMCallback*`, мультимодальные теги в `RKLLMInput.multimodal_input.image.*`.
- **librknnrt 2.3.2** (тот же тег; в 1.3.1 не менялся относительно 1.2.3).

## Обновление

```bash
# полный чекаут окружения rknn-llm нужного релиза:
cd ~/rknn-llm && git fetch --tags && git checkout release-v1.3.1

cd ~/RDS-2P-software/ros_packages/src/rkllm_ros2
cp ~/rknn-llm/rkllm-runtime/Linux/librkllm_api/include/rkllm.h       vendor/include/
cp ~/rknn-llm/rkllm-runtime/Linux/librkllm_api/aarch64/librkllmrt.so vendor/lib/
cp ~/rknn-llm/examples/multimodal_model_demo/deploy/3rdparty/librknnrt/Linux/librknn_api/include/rknn_api.h   vendor/include/
cp ~/rknn-llm/examples/multimodal_model_demo/deploy/3rdparty/librknnrt/Linux/librknn_api/aarch64/librknnrt.so vendor/lib/
```

Проверка версий:

```bash
strings vendor/lib/librkllmrt.so | grep "RKLLM SDK"      # version: 1.3.1
strings vendor/lib/librknnrt.so | grep "librknnrt version"
```

Далее `colcon build --packages-select rkllm_ros2` — запуск и RPATH см. README пакета
(launch добавляет `vendor/lib` первым в `LD_LIBRARY_PATH`).

**Важно:** версия runtime в `vendor/` должна быть **не ниже** toolkit-версии, которой
сконвертирован `.rkllm` (иначе RKLLM откажется грузить модель; см. лог при старте ноды).