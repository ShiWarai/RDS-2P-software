cmake_minimum_required(VERSION 3.8)
project(rds_2p_audio)

find_package(ament_cmake REQUIRED)

# Установка launch файлов
install(DIRECTORY launch
  DESTINATION share/${PROJECT_NAME}
)

install(PROGRAMS
  scripts/audio_player_node.py
  DESTINATION lib/${PROJECT_NAME}
)

ament_package()

