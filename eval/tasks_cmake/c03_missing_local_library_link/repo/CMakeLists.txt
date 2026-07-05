cmake_minimum_required(VERSION 3.16)
project(C03MissingLocalLink LANGUAGES CXX)

enable_testing()

add_library(mathx src/add.cpp)
target_include_directories(mathx PUBLIC include)

add_executable(app src/main.cpp)
add_test(NAME app_runs COMMAND app)
