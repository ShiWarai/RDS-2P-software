cmake_minimum_required(VERSION 3.8)
project(rds_2p_commands)

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

# Generate interfaces (должно быть ДО установки Python пакета)
rosidl_generate_interfaces(${PROJECT_NAME}
  "action/Say.action"
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

# Install Python package directory manually (т.к. rosidl_generate_interfaces конфликтует с ament_python_install_package)
install(DIRECTORY
  rds_2p_commands/
  DESTINATION lib/python3.10/site-packages/${PROJECT_NAME}
  FILES_MATCHING
  PATTERN "*.py"
  PATTERN "__pycache__" EXCLUDE
  PATTERN "*.pyc" EXCLUDE
)

# Устанавливаем все сгенерированные интерфейсы из build директории
# Это включает action модуль и все необходимые библиотеки (.so файлы)
install(DIRECTORY
  ${CMAKE_CURRENT_BINARY_DIR}/rosidl_generator_py/${PROJECT_NAME}/
  DESTINATION lib/python3.10/site-packages/${PROJECT_NAME}
  FILES_MATCHING
  PATTERN "*.py"
  PATTERN "*.so"
  PATTERN "__pycache__" EXCLUDE
  PATTERN "*.pyc" EXCLUDE
)

# Install Python scripts as executables
install(PROGRAMS
  rds_2p_commands/command_parser_node.py
  DESTINATION lib/${PROJECT_NAME}
  RENAME command_parser
)

install(PROGRAMS
  rds_2p_commands/unified_action_server.py
  DESTINATION lib/${PROJECT_NAME}
  RENAME unified_action_server
)

# Install launch files
install(DIRECTORY
  launch/
  DESTINATION share/${PROJECT_NAME}/launch
)

# Install config files
install(DIRECTORY
  config/
  DESTINATION share/${PROJECT_NAME}/config
)

# Удаляем директорию local/lib, созданную ament_cmake_python, т.к. мы используем ручную установку
install(CODE "file(REMOVE_RECURSE \"${CMAKE_INSTALL_PREFIX}/local\")")

ament_package()

