cmake_minimum_required(VERSION 3.16)
project(C01MissingHeader LANGUAGES CXX)

enable_testing()

add_executable(app src/main.cpp)
add_test(NAME app_runs COMMAND app)
