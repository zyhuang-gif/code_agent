cmake_minimum_required(VERSION 3.16)
project(C04WrongTargetName LANGUAGES CXX)

enable_testing()

add_library(mathx src/add.cpp)
target_include_directories(mathx PUBLIC include)

add_executable(app src/main.cpp)
target_link_libraries(app PRIVATE MathX::Core)
add_test(NAME app_runs COMMAND app)
