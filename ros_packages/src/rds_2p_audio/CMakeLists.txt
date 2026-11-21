cmake_minimum_required(VERSION 3.8)
project(rds_2p_audio)

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(audio_common_msgs REQUIRED)
find_package(audio_common REQUIRED)
find_package(audio_common_dsp REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_library(PORTAUDIO_LIB portaudio REQUIRED)

# Общие интерфейсы распознавания речи и TTS (vosk_ros, gigaam_ros, paroli_ros)
rosidl_generate_interfaces(${PROJECT_NAME}
  "msg/Transcription.msg"
  "msg/GrammarConfig.msg"
  "action/STT.action"
  "srv/Speak.srv"
)

# C++ плеер (pull-микшер PortAudio). Ресемплер — audio_common_dsp (4.1.0+).
add_executable(audio_player_node
  src/audio_player_node.cpp
)
ament_target_dependencies(audio_player_node
  rclcpp
  audio_common_msgs
)
target_link_libraries(audio_player_node
  ${PORTAUDIO_LIB}
  audio_common_dsp::audio_common_dsp
)
install(TARGETS
  audio_player_node
  DESTINATION lib/${PROJECT_NAME}
)

# Установка launch файлов
install(DIRECTORY launch
  DESTINATION share/${PROJECT_NAME}
)

ament_export_dependencies(rosidl_default_runtime)
ament_package()
