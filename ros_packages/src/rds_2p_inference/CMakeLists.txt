cmake_minimum_required(VERSION 3.8)
project(rds_2p_inference)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

# Set C++ standard
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# find dependencies
find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(ament_index_cpp REQUIRED)
find_package(rclcpp REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(nav_msgs REQUIRED)
find_package(rds_2p REQUIRED)

# Generate interfaces
rosidl_generate_interfaces(${PROJECT_NAME}
  "srv/InferenceResponse.srv"
  DEPENDENCIES std_msgs
)

# OnnxRuntime paths - automatically detect architecture
if(CMAKE_SYSTEM_PROCESSOR MATCHES "aarch64|ARM64|arm64")
  set(ONNXRUNTIME_ARCH "aarch64")
else()
  set(ONNXRUNTIME_ARCH "x64")
endif()

set(ONNXRUNTIME_ROOT ${CMAKE_CURRENT_SOURCE_DIR}/external_lib/onnxruntime-linux-${ONNXRUNTIME_ARCH}-1.19.2)
set(ONNXRUNTIME_INCLUDE_DIR ${ONNXRUNTIME_ROOT}/include)
set(ONNXRUNTIME_LIB_DIR ${ONNXRUNTIME_ROOT}/lib)

message(STATUS "Looking for OnnxRuntime at: ${ONNXRUNTIME_ROOT}")

# Check if OnnxRuntime exists
if(NOT EXISTS ${ONNXRUNTIME_INCLUDE_DIR})
  message(FATAL_ERROR "OnnxRuntime not found at ${ONNXRUNTIME_ROOT}. Please download and extract it to external_lib/")
endif()

if(BUILD_TESTING)
  find_package(ament_lint_auto REQUIRED)
  # the following line skips the linter which checks for copyrights
  # comment the line when a copyright and license is added to all source files
  set(ament_cmake_copyright_FOUND TRUE)
  # the following line skips cpplint (only works in a git repo)
  # comment the line when this package is in a git repo and when
  # a copyright and license is added to all source files
  set(ament_cmake_cpplint_FOUND TRUE)
  ament_lint_auto_find_test_dependencies()
endif()

# Include directories
include_directories(
  include
  ${ONNXRUNTIME_INCLUDE_DIR}
)

# Create inference_node executable
add_executable(inference_node 
  src/inference_node.cpp
  src/inference_controller.cpp
)

# Link libraries for inference_node
ament_target_dependencies(inference_node
  ament_index_cpp
  rclcpp
  sensor_msgs
  geometry_msgs
  nav_msgs
  rds_2p
)

# Link OnnxRuntime
target_link_libraries(inference_node
  ${ONNXRUNTIME_LIB_DIR}/libonnxruntime.so
)

# Link generated service interfaces (after executables are defined)
# Примечание: интерфейс сервиса может использоваться в других местах, поэтому оставляем
rosidl_get_typesupport_target(cpp_typesupport_target
  ${PROJECT_NAME} "rosidl_typesupport_cpp")

target_link_libraries(inference_node "${cpp_typesupport_target}")

# Install executables
install(TARGETS
  inference_node
  DESTINATION lib/${PROJECT_NAME}
)

# Install models directory
install(DIRECTORY
  models/
  DESTINATION share/${PROJECT_NAME}/models
)

# Install launch files
install(DIRECTORY
  launch/
  DESTINATION share/${PROJECT_NAME}/launch
)

# Install Python scripts
install(PROGRAMS
  scripts/virtual_twin_node.py
  DESTINATION lib/${PROJECT_NAME}
)

# Install OnnxRuntime library
install(FILES
  ${ONNXRUNTIME_LIB_DIR}/libonnxruntime.so
  ${ONNXRUNTIME_LIB_DIR}/libonnxruntime.so.1.19.2
  DESTINATION lib
)

ament_package()
