# FTServoLibrary CMakeLists.txt for ftservo_ros package

# Create FTServo library from source
add_library(ftservo_lib
    FTServoLibrary/src/SCSCL.cpp
    FTServoLibrary/src/SCS.cpp
    FTServoLibrary/src/SMS_STS.cpp
    FTServoLibrary/src/SMSBL.cpp
    FTServoLibrary/src/SMSCL.cpp
    FTServoLibrary/src/HLSCL.cpp
    FTServoLibrary/src/SCSerial.cpp
)

# Set include directories for FTServo library
target_include_directories(ftservo_lib PUBLIC
    ${CMAKE_CURRENT_SOURCE_DIR}/FTServoLibrary/include
    ${CMAKE_CURRENT_SOURCE_DIR}/FTServoLibrary/src
)

# Set C++ standard for the library
set_target_properties(ftservo_lib PROPERTIES
    CXX_STANDARD 17
    CXX_STANDARD_REQUIRED ON
)

# Link with standard libraries
target_link_libraries(ftservo_lib
    pthread
    m
)
