cmake_minimum_required(VERSION 3.8)
project(rds_2p_joystick)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

# find dependencies
find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(OpenCV REQUIRED)

if(BUILD_TESTING)
  find_package(ament_lint_auto REQUIRED)
  set(ament_cmake_copyright_FOUND TRUE)
  set(ament_cmake_cpplint_FOUND TRUE)
  ament_lint_auto_find_test_dependencies()
endif()

# Include directories
include_directories(include)

# Executable for touchpad drawer node
add_executable(touchpad_drawer
  src/touchpad_drawer.cpp
)

ament_target_dependencies(touchpad_drawer
  rclcpp
  sensor_msgs
  geometry_msgs
)

# Подключение OpenCV к touchpad_drawer
target_link_libraries(touchpad_drawer ${OpenCV_LIBS})
target_include_directories(touchpad_drawer PUBLIC ${OpenCV_INCLUDE_DIRS})

# Install executables
install(TARGETS
  touchpad_drawer
  DESTINATION lib/${PROJECT_NAME}
)

# Install header files
install(DIRECTORY include/
  DESTINATION include
)

# Install Python scripts
install(PROGRAMS
  scripts/ps4_imu_node.py
  scripts/ps4_touchpad_node.py
  DESTINATION lib/${PROJECT_NAME}
)

# Install launch files
install(DIRECTORY
  launch/
  DESTINATION share/${PROJECT_NAME}/launch
)

ament_package()

