cmake_minimum_required(VERSION 3.8)
project(rds_2p_cmd_vel_mux)

find_package(ament_cmake REQUIRED)

install(PROGRAMS
  scripts/cmd_vel_mux.py
  DESTINATION lib/${PROJECT_NAME}
)

install(DIRECTORY
  launch/
  DESTINATION share/${PROJECT_NAME}/launch
)

install(DIRECTORY
  config/
  DESTINATION share/${PROJECT_NAME}/config
)

ament_package()