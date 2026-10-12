cmake_minimum_required(VERSION 3.8)
project(rkllm_ros2)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

# Vendor RK runtime (.so + headers) — пользователь кладёт по README / vendor/README.md
if(NOT EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/vendor/lib/librkllmrt.so")
  message(FATAL_ERROR
    "Нет vendor/lib/librkllmrt.so. Скопируйте из rknn-llm rkllm-runtime (см. rkllm_ros2/vendor/README.md).")
endif()
if(NOT EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/vendor/lib/librknnrt.so")
  message(FATAL_ERROR
    "Нет vendor/lib/librknnrt.so. Скопируйте из multimodal_model_demo/deploy/3rdparty/librknnrt (см. vendor/README.md).")
endif()
if(NOT EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/vendor/include/rkllm.h")
  message(FATAL_ERROR "Нет vendor/include/rkllm.h — см. vendor/README.md.")
endif()
if(NOT EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/vendor/include/rknn_api.h")
  message(FATAL_ERROR "Нет vendor/include/rknn_api.h — см. vendor/README.md.")
endif()

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(rclcpp_action REQUIRED)
find_package(rkllm_ros2_msgs REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(std_msgs REQUIRED)
find_package(std_srvs REQUIRED)
find_package(cv_bridge REQUIRED)
find_package(OpenCV REQUIRED)

add_executable(rkllm_node
  src/rkllm_node.cpp
  src/image_enc.cc
)

if(CMAKE_CXX_COMPILER_ID MATCHES "Clang|GNU")
  set_source_files_properties(src/image_enc.cc PROPERTIES
    COMPILE_FLAGS "-Wno-vla -Wno-unused-variable -Wno-sign-compare")
endif()

target_include_directories(rkllm_node PRIVATE
  ${CMAKE_CURRENT_SOURCE_DIR}/src
  ${CMAKE_CURRENT_SOURCE_DIR}/vendor/include
)

target_link_libraries(rkllm_node
  ${OpenCV_LIBS}
  "${CMAKE_CURRENT_SOURCE_DIR}/vendor/lib/librkllmrt.so"
  "${CMAKE_CURRENT_SOURCE_DIR}/vendor/lib/librknnrt.so"
)

ament_target_dependencies(rkllm_node
  rclcpp
  rclcpp_action
  sensor_msgs
  std_msgs
  std_srvs
  cv_bridge
)

rosidl_get_typesupport_target(cpp_typesupport_target "rkllm_ros2_msgs" "rosidl_typesupport_cpp")
target_link_libraries(rkllm_node "${cpp_typesupport_target}")

# Исполняемый файл: lib/<pkg>/rkllm_node, .so: lib/<pkg>/vendor/lib → $ORIGIN/vendor/lib
set_target_properties(rkllm_node PROPERTIES
  INSTALL_RPATH "$ORIGIN/vendor/lib"
  BUILD_RPATH "${CMAKE_CURRENT_SOURCE_DIR}/vendor/lib"
  BUILD_WITH_INSTALL_RPATH TRUE
)

install(TARGETS rkllm_node
  DESTINATION lib/${PROJECT_NAME})

install(DIRECTORY vendor/lib/
  DESTINATION lib/${PROJECT_NAME}/vendor/lib)

install(DIRECTORY launch/
  DESTINATION share/${PROJECT_NAME}/launch)

install(PROGRAMS
  scripts/example_chat.py
  scripts/example_vision.py
  DESTINATION lib/${PROJECT_NAME})

if(BUILD_TESTING)
  find_package(ament_lint_auto REQUIRED)
  set(ament_cmake_copyright_FOUND TRUE)
  set(ament_cmake_cpplint_FOUND TRUE)
  ament_lint_auto_find_test_dependencies()
endif()

ament_package()
