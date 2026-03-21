cmake_minimum_required(VERSION 3.8)
project(rds_2p_dance)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

# find dependencies
find_package(ament_cmake REQUIRED)
find_package(ament_cmake_python REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(action_msgs REQUIRED)
find_package(unique_identifier_msgs REQUIRED)
find_package(builtin_interfaces REQUIRED)

# Generate interfaces
rosidl_generate_interfaces(${PROJECT_NAME}
  "action/PlayDance.action"
  DEPENDENCIES action_msgs unique_identifier_msgs builtin_interfaces
)

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

# Install Python scripts
install(PROGRAMS
  scripts/dance_action_server.py
  DESTINATION lib/${PROJECT_NAME}
  RENAME dance_action_server
)

install(PROGRAMS
  scripts/dance_joy_controller.py
  DESTINATION lib/${PROJECT_NAME}
  RENAME dance_joy_controller
)

# Install animations directory
install(DIRECTORY
  animations/
  DESTINATION share/${PROJECT_NAME}/animations
  FILES_MATCHING PATTERN "*.csv"
)

# Install launch files
install(DIRECTORY
  launch/
  DESTINATION share/${PROJECT_NAME}/launch
)

ament_package()

