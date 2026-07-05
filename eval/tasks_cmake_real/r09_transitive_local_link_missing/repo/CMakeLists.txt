cmake_minimum_required(VERSION 3.16)
project(R09TransitiveLocalLink LANGUAGES CXX)

enable_testing()

add_library(mathcore src/core.cpp)
target_include_directories(mathcore PUBLIC include)

add_library(mathapp src/app_math.cpp)
target_include_directories(mathapp PUBLIC include)

add_executable(app src/main.cpp)
target_link_libraries(app PRIVATE mathapp)
add_test(NAME app_runs COMMAND app)
