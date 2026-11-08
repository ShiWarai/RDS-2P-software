cmake_minimum_required(VERSION 3.8)
project(paroli_ros2)

find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)

if(NOT EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/vendor/paroli-cli")
  message(
    FATAL_ERROR
    "Нет vendor/paroli-cli. Скопируйте paroli-cli и vendor/lib из сборки paroli-tts (см. README.md).")
endif()

rosidl_generate_interfaces(${PROJECT_NAME}
  "srv/Speak.srv"
)

install(PROGRAMS
  scripts/tts_node.py
  vendor/paroli-cli
  DESTINATION lib/${PROJECT_NAME})

# vendor/lib (*.so из сборки paroli-tts) есть только на роботе;
# на десктопе собираем интерфейс и ставим ноду, тогда без .so (озвучка не запустится)
if(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/vendor/lib")
  install(DIRECTORY vendor/lib/
    DESTINATION lib/${PROJECT_NAME}/vendor/lib)
else()
  message(WARNING
    "Нет vendor/lib/ (*.so из сборки paroli-tts) — паркуем интерфейс и ноду без них; "
    "на этом устройстве paroli-cli/озвучка работать не будет.")
endif()

install(DIRECTORY launch DESTINATION share/${PROJECT_NAME})

install(DIRECTORY models/
  DESTINATION share/${PROJECT_NAME}/models)

ament_export_dependencies(rosidl_default_runtime)
ament_package()
