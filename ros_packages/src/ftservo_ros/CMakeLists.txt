cmake_minimum_required(VERSION 3.8)
project(ftservo_ros)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

# Find dependencies
find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(std_msgs REQUIRED)
find_package(yaml-cpp REQUIRED)
find_package(rosidl_default_generators REQUIRED)

# Include directories
include_directories(
  include
  library/FTServoLibrary/include
  library/FTServoLibrary/src
)

# Generate messages first
rosidl_generate_interfaces(${PROJECT_NAME}
  "msg/MotorCommand.msg"
  "msg/MotorCommands.msg"
  "msg/MotorParam.msg"
  "msg/MotorParams.msg"
  "msg/MotorState.msg"
  "msg/MotorStates.msg"
  "msg/MotorTelemetry.msg"
  "msg/MotorTelemetries.msg"
  "msg/MotorJointBinding.msg"
  "msg/MotorJointMapping.msg"
  DEPENDENCIES std_msgs
)

# Add FTServoLibrary subdirectory to build the library
add_subdirectory(${CMAKE_CURRENT_SOURCE_DIR}/library)

# Motor config library
add_library(motor_config_lib
  src/motor_config.cpp
)

ament_target_dependencies(motor_config_lib
  rclcpp
  std_msgs
)

target_link_libraries(motor_config_lib
  yaml-cpp
)

# Motor controller library
add_library(motor_controller_lib
  src/motor_controller.cpp
)

ament_target_dependencies(motor_controller_lib
  rclcpp
  std_msgs
)

target_link_libraries(motor_controller_lib
  motor_config_lib
)

# Add dependency on generated messages for libraries
rosidl_get_typesupport_target(cpp_typesupport_target
  ${PROJECT_NAME} "rosidl_typesupport_cpp")
target_link_libraries(motor_config_lib "${cpp_typesupport_target}")
target_link_libraries(motor_controller_lib "${cpp_typesupport_target}")

# Main executable
add_executable(motor_controller_node
  src/motor_controller_node.cpp
)

ament_target_dependencies(motor_controller_node
  rclcpp
  std_msgs
)

target_link_libraries(motor_controller_node
  motor_controller_lib
  motor_config_lib
  ftservo_lib
)

# Add dependency on generated messages
rosidl_get_typesupport_target(cpp_typesupport_target
  ${PROJECT_NAME} "rosidl_typesupport_cpp")
target_link_libraries(motor_controller_node "${cpp_typesupport_target}")

# Install
install(TARGETS
  motor_controller_node
  motor_controller_lib
  motor_config_lib
  ftservo_lib
  ARCHIVE DESTINATION lib
  LIBRARY DESTINATION lib
  RUNTIME DESTINATION lib/${PROJECT_NAME}
)

install(DIRECTORY
  include/
  DESTINATION include/
)

install(DIRECTORY
  launch
  config
  DESTINATION share/${PROJECT_NAME}
)

# Install Python scripts
file(COPY scripts/motor_gui.py DESTINATION ${CMAKE_CURRENT_BINARY_DIR}/scripts FILE_PERMISSIONS OWNER_READ OWNER_WRITE OWNER_EXECUTE GROUP_READ GROUP_EXECUTE WORLD_READ WORLD_EXECUTE)

install(PROGRAMS
  ${CMAKE_CURRENT_BINARY_DIR}/scripts/motor_gui.py
  DESTINATION lib/${PROJECT_NAME}
)

if(BUILD_TESTING)
  find_package(ament_lint_auto REQUIRED)
  ament_lint_auto_find_test_dependencies()
endif()

ament_package() 