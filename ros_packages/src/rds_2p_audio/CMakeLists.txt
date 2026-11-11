cmake_minimum_required(VERSION 3.8)
project(rds_2p_audio)

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(audio_common_msgs REQUIRED)
find_package(audio_common REQUIRED)
find_library(PORTAUDIO_LIB portaudio REQUIRED)

# C++ плеер (pull-микшер PortAudio)
add_executable(audio_player_node
  src/audio_player_node.cpp
)
ament_target_dependencies(audio_player_node
  rclcpp
  audio_common_msgs
  audio_common
)
target_link_libraries(audio_player_node
  ${PORTAUDIO_LIB}
  ${audio_common_LIBRARIES}
)
install(TARGETS
  audio_player_node
  DESTINATION lib/${PROJECT_NAME}
)

# Установка launch файлов
install(DIRECTORY launch
  DESTINATION share/${PROJECT_NAME}
)

ament_package()
