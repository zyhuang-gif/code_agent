cmake_minimum_required(VERSION 3.16)
project(M01WithoutMemory LANGUAGES CXX)

enable_testing()

add_executable(app src/main.cpp)
add_test(NAME app_runs COMMAND app)
