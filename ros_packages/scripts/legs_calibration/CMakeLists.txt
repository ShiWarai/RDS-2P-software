cmake_minimum_required(VERSION 3.10)
project(servo_calibration VERSION 1.0.0 LANGUAGES CXX)

# Устанавливаем стандарт C++
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Добавляем опции компиляции
if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra)
endif()

# Находим зависимости
find_package(nlohmann_json REQUIRED)

# Директории с заголовочными файлами
include_directories(
  ${CMAKE_SOURCE_DIR}/../../src/ftservo_ros/library/FTServoLibrary/include
  ${CMAKE_SOURCE_DIR}/../../src/ftservo_ros/library/FTServoLibrary/src
)

# Собираем FTServoLibrary как статическую библиотеку
add_library(ftservo_lib STATIC
  ../../src/ftservo_ros/library/FTServoLibrary/src/SCS.cpp
  ../../src/ftservo_ros/library/FTServoLibrary/src/SCSerial.cpp
  ../../src/ftservo_ros/library/FTServoLibrary/src/SCSCL.cpp
)

target_include_directories(ftservo_lib PUBLIC
  ${CMAKE_SOURCE_DIR}/../../src/ftservo_ros/library/FTServoLibrary/include
  ${CMAKE_SOURCE_DIR}/../../src/ftservo_ros/library/FTServoLibrary/src
)

# Создаём исполняемый файл калибровки
add_executable(servo_calibration
  src/servo_calibration.cpp
)

target_include_directories(servo_calibration PRIVATE
  ${CMAKE_SOURCE_DIR}/../../src/ftservo_ros/library/FTServoLibrary/include
)

# Линкуем библиотеки
target_link_libraries(servo_calibration
  ftservo_lib
  nlohmann_json::nlohmann_json
)

# Установка (опционально)
install(TARGETS servo_calibration
  RUNTIME DESTINATION bin
)

# Вывод информации о сборке
message(STATUS "Servo Calibration ${PROJECT_VERSION}")
message(STATUS "Build type: ${CMAKE_BUILD_TYPE}")
message(STATUS "C++ Standard: ${CMAKE_CXX_STANDARD}")
