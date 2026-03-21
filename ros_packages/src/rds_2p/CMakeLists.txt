
cmake_minimum_required(VERSION 3.8)
project(rds_2p)

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(std_msgs REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(nav_msgs REQUIRED)
find_package(ftservo_ros REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(tf2_ros REQUIRED)
find_package(tf2 REQUIRED)
find_package(yaml-cpp REQUIRED)

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

# Создание исполняемого файла
add_executable(motor_to_joint_bridge
  src/motor_to_joint_bridge.cpp
)

# Создание исполняемого файла для IMU трансформации
add_executable(imu_transform_publisher
  src/imu_transform_publisher.cpp
)

# Создание статических трансформаций
add_executable(static_transform_publisher
  src/static_transform_publisher.cpp
)

# Создание библиотеки кинематики ноги
add_library(leg_kinematics
  src/leg_kinematics.cpp
)

target_include_directories(leg_kinematics PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
  $<INSTALL_INTERFACE:include>
)

# Добавляем include директории для всех целей
include_directories(include)

# Создание моста джоинтов к моторам
add_executable(joint_to_motor_bridge
  src/joint_to_motor_bridge.cpp
)

# Создание фейкового IMU паблишера
add_executable(fake_imu_publisher
  src/fake_imu_publisher.cpp
)

# Создание ноды мониторинга батареи
add_executable(battery_monitor
  src/battery_monitor.cpp
)




ament_target_dependencies(motor_to_joint_bridge
  rclcpp
  std_msgs
  sensor_msgs
  ftservo_ros
)

ament_target_dependencies(imu_transform_publisher
  rclcpp
  std_msgs
  sensor_msgs
  geometry_msgs
  tf2_ros
)

ament_target_dependencies(static_transform_publisher
  rclcpp
  tf2_ros
)

ament_target_dependencies(joint_to_motor_bridge
  rclcpp
  std_msgs
  sensor_msgs
  ftservo_ros
)

ament_target_dependencies(fake_imu_publisher
  rclcpp
  sensor_msgs
  geometry_msgs
)

ament_target_dependencies(battery_monitor
  rclcpp
  sensor_msgs
  ftservo_ros
)

target_link_libraries(joint_to_motor_bridge
  yaml-cpp
  leg_kinematics
)








target_link_libraries(motor_to_joint_bridge
  yaml-cpp
)

# Установка исполняемых файлов и библиотек
install(TARGETS
  motor_to_joint_bridge
  imu_transform_publisher
  static_transform_publisher
  joint_to_motor_bridge
  fake_imu_publisher
  battery_monitor
  leg_kinematics
  DESTINATION lib/${PROJECT_NAME}
)

# Установка Python скриптов
install(PROGRAMS
  src/keyframe_console.py
  src/joint_comparison.py
  DESTINATION lib/${PROJECT_NAME}
)

# Установка заголовочных файлов
install(DIRECTORY include/
  DESTINATION include
)

# Установка ресурсов
install(DIRECTORY launch meshes rviz urdf worlds config
  DESTINATION share/${PROJECT_NAME}
)
ament_package()
