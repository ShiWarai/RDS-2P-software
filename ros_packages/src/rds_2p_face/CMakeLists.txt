cmake_minimum_required(VERSION 3.8)
project(rds_2p_face)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(cv_bridge REQUIRED)
find_package(image_transport REQUIRED)
find_package(OpenCV REQUIRED)

# Поиск библиотеки gpiod
find_library(GPIOD_LIBRARY
  NAMES gpiod
  PATHS /usr/lib /usr/local/lib
)

if(NOT GPIOD_LIBRARY)
  message(FATAL_ERROR "Библиотека gpiod не найдена. Установите: sudo apt-get install libgpiod-dev")
endif()

# Include directories
include_directories(include)

# Executable for display face node
add_executable(display_face
  src/display_face.cpp
)

ament_target_dependencies(display_face
  rclcpp
  sensor_msgs
)

# Подключение gpiod к display_face
target_link_libraries(display_face ${GPIOD_LIBRARY})

# Executable for image processor node
add_executable(image_processor
  src/image_processor.cpp
)

ament_target_dependencies(image_processor
  rclcpp
  sensor_msgs
  cv_bridge
  image_transport
)

# Install executables
install(TARGETS
  display_face
  image_processor
  DESTINATION lib/${PROJECT_NAME}
)

# Install header files
install(DIRECTORY include/
  DESTINATION include
)

# Install launch files
install(DIRECTORY launch/
  DESTINATION share/${PROJECT_NAME}/launch
)

# Install scripts
install(PROGRAMS
  scripts/publish_image.py
  scripts/lip_sync_face_node.py
  DESTINATION lib/${PROJECT_NAME}
)

install(FILES config/lip_sync_manifest.json
  DESTINATION share/${PROJECT_NAME}/config
)

install(DIRECTORY data/lip_sync/
  DESTINATION share/${PROJECT_NAME}/data/lip_sync
)

if(BUILD_TESTING)
  find_package(ament_lint_auto REQUIRED)
  ament_lint_auto_find_test_dependencies()
endif()

ament_package()

