cmake_minimum_required(VERSION 3.8)
project(ros2_perf_test)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

# Find dependencies
find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(std_msgs REQUIRED)
find_package(ftservo_ros REQUIRED)

# Ping node executable
add_executable(ping_node src/ping_node.cpp)
ament_target_dependencies(ping_node
  rclcpp
  std_msgs
  ftservo_ros
)

# Pong node executable
add_executable(pong_node src/pong_node.cpp)
ament_target_dependencies(pong_node
  rclcpp
  std_msgs
  ftservo_ros
)

# Install executables
install(TARGETS
  ping_node
  pong_node
  DESTINATION lib/${PROJECT_NAME}
)

if(BUILD_TESTING)
  find_package(ament_lint_auto REQUIRED)
  ament_lint_auto_find_test_dependencies()
endif()

ament_package()

