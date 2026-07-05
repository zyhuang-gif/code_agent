cmake_minimum_required(VERSION 3.16)
project(R06GeneratedConfig LANGUAGES CXX)

enable_testing()

configure_file(config/app_config.hpp.in generated/app_config.hpp @ONLY)
add_executable(app src/main.cpp)
add_test(NAME app_runs COMMAND app)
