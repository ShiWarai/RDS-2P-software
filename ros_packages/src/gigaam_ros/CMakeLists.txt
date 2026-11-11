cmake_minimum_required(VERSION 3.8)
project(gigaam_ros)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

# Find dependencies
find_package(ament_cmake REQUIRED)
find_package(ament_cmake_python REQUIRED)
find_package(rclpy REQUIRED)
find_package(std_msgs REQUIRED)
find_package(Python3 COMPONENTS Interpreter Development REQUIRED)

# Интерфейсы Transcription/GrammarConfig/STT теперь общие — в rds_2p_audio.

# Install Python executables.
# rknn_engine.py is a plain module installed alongside the nodes into
# lib/${PROJECT_NAME}; the nodes add that directory to sys.path at runtime and
# import it.
install(PROGRAMS
  src/gigaam_node.py
  DESTINATION lib/${PROJECT_NAME}
  RENAME gigaam_node
)

install(PROGRAMS
  src/vad_node.py
  DESTINATION lib/${PROJECT_NAME}
  RENAME vad_node
)

install(FILES
  src/rknn_engine.py
  DESTINATION lib/${PROJECT_NAME}
)

# Install launch files
install(DIRECTORY launch
  DESTINATION share/${PROJECT_NAME}
)

# Install model files (models/ is gitignored; place *.rknn / vocab / vad here)
install(DIRECTORY models
  DESTINATION share/${PROJECT_NAME}
)

ament_package()
