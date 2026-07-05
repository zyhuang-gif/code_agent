cmake_minimum_required(VERSION 3.16)
project(R04Gperftools LANGUAGES CXX)

enable_testing()

add_executable(app src/main.cpp)
target_link_libraries(app PRIVATE gperftools::profiler)
add_test(NAME app_runs COMMAND app)
