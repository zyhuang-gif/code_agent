cmake_minimum_required(VERSION 3.16)
project(R02NlohmannJson LANGUAGES CXX)

enable_testing()

find_package(nlohmann_json REQUIRED)

add_executable(app src/main.cpp)
target_link_libraries(app PRIVATE nlohmann_json::nlohmann_json)
add_test(NAME app_runs COMMAND app)
