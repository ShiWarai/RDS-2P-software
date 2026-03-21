cmake_minimum_required(VERSION 3.8)
project(mtf02p_ros)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED True)

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(nav_msgs REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(tf2_ros REQUIRED)
find_package(std_msgs REQUIRED)
find_package(sensor_msgs REQUIRED)

include_directories(include)

add_library(kalman_filter_lib
  src/kalman_filter.cpp
)

add_library(micolink_parser_lib
  src/micolink_parser.cpp
)

add_library(uart_reader_lib
  src/uart_reader.cpp
)

ament_target_dependencies(kalman_filter_lib
  rclcpp
)

ament_target_dependencies(micolink_parser_lib
  rclcpp
)

target_link_libraries(uart_reader_lib
  micolink_parser_lib
)

ament_target_dependencies(uart_reader_lib
  rclcpp
)

add_executable(mtf02p_odom_node src/mtf02p_odom_node.cpp)

target_link_libraries(mtf02p_odom_node
  kalman_filter_lib
  micolink_parser_lib
  uart_reader_lib
  pthread
)

ament_target_dependencies(mtf02p_odom_node
  rclcpp
  nav_msgs
  geometry_msgs
  tf2_ros
  std_msgs
)

add_executable(odom_fusion_node src/odom_fusion_node.cpp)

ament_target_dependencies(odom_fusion_node
  rclcpp
  nav_msgs
  geometry_msgs
  sensor_msgs
  tf2_ros
  std_msgs
)

install(TARGETS
  mtf02p_odom_node
  odom_fusion_node
  DESTINATION lib/${PROJECT_NAME}
)

install(DIRECTORY
  launch
  DESTINATION share/${PROJECT_NAME}
)

if(BUILD_TESTING)
  find_package(ament_lint_auto REQUIRED)
  ament_lint_auto_find_test_dependencies()
endif()

ament_package()
