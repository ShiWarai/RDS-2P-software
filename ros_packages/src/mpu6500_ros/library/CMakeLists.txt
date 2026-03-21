# MPU6500 Library CMakeLists.txt

# Create mpu6500 library
add_library(mpu6500_lib
    mpu6500/src/driver_mpu6500.c
)

target_include_directories(mpu6500_lib PUBLIC
    ${CMAKE_CURRENT_SOURCE_DIR}/mpu6500/src
    ${CMAKE_CURRENT_SOURCE_DIR}/mpu6500/interface
)

# Create interface library
add_library(interface_lib
    mpu6500/project/raspberrypi4b/driver/src/raspberrypi4b_driver_mpu6500_interface.c
    mpu6500/project/raspberrypi4b/interface/src/iic.c
    mpu6500/project/raspberrypi4b/interface/src/spi.c
    mpu6500/project/raspberrypi4b/interface/src/gpio.c
    mpu6500/project/raspberrypi4b/interface/src/mutex.c
)

target_include_directories(interface_lib PUBLIC
    ${CMAKE_CURRENT_SOURCE_DIR}/mpu6500/interface
    ${CMAKE_CURRENT_SOURCE_DIR}/mpu6500/src
    ${CMAKE_CURRENT_SOURCE_DIR}/mpu6500/project/raspberrypi4b/driver/src
    ${CMAKE_CURRENT_SOURCE_DIR}/mpu6500/project/raspberrypi4b/interface/inc
)

# Create driver library (basic/fifo/dmp functions)
# Check if we have example directory with these functions
file(GLOB EXAMPLE_SOURCES
    "mpu6500/example/*.c"
)

# Check if we have test directory with additional functions
file(GLOB TEST_SOURCES
    "mpu6500/test/*.c"
)

# Combine all sources
set(DRIVER_SOURCES ${EXAMPLE_SOURCES} ${TEST_SOURCES})

if(DRIVER_SOURCES)
    add_library(driver_lib ${DRIVER_SOURCES})
    target_include_directories(driver_lib PUBLIC
        ${CMAKE_CURRENT_SOURCE_DIR}/mpu6500/example
        ${CMAKE_CURRENT_SOURCE_DIR}/mpu6500/test
        ${CMAKE_CURRENT_SOURCE_DIR}/mpu6500/src
        ${CMAKE_CURRENT_SOURCE_DIR}/mpu6500/interface
    )
    target_link_libraries(driver_lib mpu6500_lib interface_lib)
else()
    # Create empty driver lib if no examples found
    add_library(driver_lib INTERFACE)
endif()

# Link libraries
target_link_libraries(mpu6500_lib interface_lib m)
