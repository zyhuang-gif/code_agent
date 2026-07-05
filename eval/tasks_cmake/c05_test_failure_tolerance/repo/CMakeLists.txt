cmake_minimum_required(VERSION 3.16)
project(C05TestFailure LANGUAGES CXX)

enable_testing()

add_executable(app src/main.cpp src/scale.cpp)
target_include_directories(app PRIVATE include)
add_test(NAME app_runs COMMAND app)
