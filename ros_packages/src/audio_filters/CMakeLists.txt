cmake_minimum_required(VERSION 3.16)
project(audio_filters)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

set(CMAKE_CXX_STANDARD 17)

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(std_msgs REQUIRED)
find_package(audio_common_msgs REQUIRED)
find_package(PkgConfig REQUIRED)

pkg_check_modules(SOXR REQUIRED soxr)

# RNNoise: собирается заранее скриптами scripts/build_for_{robot,desktop}.sh → deps/rnnoise_install/
get_filename_component(_ros_pkg_root "${CMAKE_CURRENT_SOURCE_DIR}/../.." ABSOLUTE)
set(RNN_INST "${_ros_pkg_root}/deps/rnnoise_install")

if(NOT EXISTS "${RNN_INST}/lib/librnnoise.a")
  message(
    FATAL_ERROR
      "Не найдена статическая библиотека RNNoise (${RNN_INST}/lib/librnnoise.a). "
      "Сначала запустите scripts/build_for_robot.sh или scripts/build_for_desktop.sh "
      "(они клонируют rnnoise и делают make install в deps/rnnoise_install), затем colcon build.")
endif()
if(NOT EXISTS "${RNN_INST}/include/rnnoise.h")
  message(
    FATAL_ERROR
      "Не найден rnnoise.h в ${RNN_INST}/include. Пересоберите deps через build_for_robot/desktop.sh.")
endif()

add_executable(audio_rnnoise_node src/audio_rnnoise_node.cpp)

target_include_directories(
  audio_rnnoise_node PRIVATE
  "${RNN_INST}/include"
  ${SOXR_INCLUDE_DIRS})

ament_target_dependencies(
  audio_rnnoise_node
  rclcpp
  std_msgs
  audio_common_msgs
)

target_link_libraries(
  audio_rnnoise_node
  "${RNN_INST}/lib/librnnoise.a"
  ${SOXR_LIBRARIES}
  m
)

add_executable(audio_gain_node src/audio_gain_node.cpp)
ament_target_dependencies(
  audio_gain_node
  rclcpp
  std_msgs
  audio_common_msgs)

install(TARGETS audio_rnnoise_node audio_gain_node DESTINATION lib/${PROJECT_NAME})
install(DIRECTORY launch DESTINATION share/${PROJECT_NAME})

if(BUILD_TESTING)
  find_package(ament_lint_auto REQUIRED)
  ament_lint_auto_find_test_dependencies()
endif()

ament_package()
