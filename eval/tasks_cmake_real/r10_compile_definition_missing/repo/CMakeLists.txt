cmake_minimum_required(VERSION 3.16)
project(R10CompileDefinition LANGUAGES CXX)

enable_testing()

add_executable(app src/main.cpp)
add_test(NAME feature_enabled COMMAND app)
