cmake_minimum_required(VERSION 3.16)
project(R07CTestWorkingDirectory LANGUAGES CXX)

enable_testing()

add_executable(app src/main.cpp)
add_test(NAME reads_fixture COMMAND app)
