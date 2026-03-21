#
# Copyright (c) 2015 - present LibDriver All rights reserved
#
# The MIT License (MIT)
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
#

# set the cmake minimum version
cmake_minimum_required(VERSION 3.8)

# set the project name and language
project(mpu6500_ros)

# Set C and C++ standards
set(CMAKE_C_STANDARD 99)
set(CMAKE_C_STANDARD_REQUIRED True)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED True)

if(CMAKE_COMPILER_IS_GNUCC OR CMAKE_C_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

# find dependencies
find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(std_msgs REQUIRED)
find_package(geometry_msgs REQUIRED)

# find the pkgconfig and use this tool to find the third party packages
find_package(PkgConfig REQUIRED)

# find the third party packages with pkgconfig
pkg_search_module(GPIOD REQUIRED libgpiod)

# include all library header directories for MPU6500 library
set(MPU6500_INCLUDE_DIRS
    ${CMAKE_CURRENT_SOURCE_DIR}/library
    ${CMAKE_CURRENT_SOURCE_DIR}/library/mpu6500
    ${CMAKE_CURRENT_SOURCE_DIR}/library/mpu6500/test
)

# include all library header directories for MPU6500 library
include_directories(${MPU6500_INCLUDE_DIRS})

# include gpiod headers
include_directories(${GPIOD_INCLUDE_DIRS})

# include all library source directories for MPU6500 library
add_subdirectory(${CMAKE_CURRENT_SOURCE_DIR}/library)

# create the mpu6500_ros executable
add_executable(mpu6500_imu_node src/mpu6500_imu_node.cpp)

# link the mpu6500_ros executable with the MPU6500 library
target_link_libraries(mpu6500_imu_node
    ${GPIOD_LIBRARIES}
    m  # Math library for asinf, etc.
    mpu6500_lib
    interface_lib
    driver_lib
)

# add gpiod link flags
target_link_libraries(mpu6500_imu_node ${GPIOD_LDFLAGS})

# link with ROS2 libraries
ament_target_dependencies(mpu6500_imu_node
    rclcpp
    sensor_msgs
    std_msgs
    geometry_msgs
)

# create the mpu6500 simple imu executable
add_executable(mpu6500_simple_imu_node src/mpu6500_simple_imu_node.cpp)

# link the mpu6500 simple imu executable with the MPU6500 library
target_link_libraries(mpu6500_simple_imu_node
    ${GPIOD_LIBRARIES}
    m  # Math library for asinf, etc.
    mpu6500_lib
    interface_lib
    driver_lib
)

# add gpiod link flags
target_link_libraries(mpu6500_simple_imu_node ${GPIOD_LDFLAGS})

# link with ROS2 libraries
ament_target_dependencies(mpu6500_simple_imu_node
    rclcpp
    sensor_msgs
    std_msgs
    geometry_msgs
)



# install the mpu6500_ros executable
install(TARGETS
    mpu6500_imu_node
    mpu6500_simple_imu_node
    DESTINATION lib/${PROJECT_NAME}
)

# install the launch files
install(DIRECTORY
    launch
    DESTINATION share/${PROJECT_NAME}
)

# export the package
ament_package()
