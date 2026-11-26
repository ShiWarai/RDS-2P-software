cmake_minimum_required(VERSION 3.8)
project(system_one_ros)

find_package(ament_cmake REQUIRED)
find_package(llm_msgs_ros REQUIRED)

install(DIRECTORY
  launch/
  DESTINATION share/${PROJECT_NAME}/launch
)

install(DIRECTORY
  osm_app/
  DESTINATION lib/${PROJECT_NAME}/osm_app
)

install(PROGRAMS
  scripts/system_one_client.py
  DESTINATION lib/${PROJECT_NAME}
  RENAME system_one_client
)

install(PROGRAMS
  scripts/system_one_native.py
  DESTINATION lib/${PROJECT_NAME}
  RENAME system_one_native
)

install(PROGRAMS
  scripts/example_ask.py
  DESTINATION lib/${PROJECT_NAME}
  RENAME example_ask
)


if(BUILD_TESTING)
  find_package(ament_lint_auto REQUIRED)
  set(ament_cmake_copyright_FOUND TRUE)
  set(ament_cmake_cpplint_FOUND TRUE)
  ament_lint_auto_find_test_dependencies()
endif()

ament_export_dependencies(llm_msgs_ros)
ament_package()