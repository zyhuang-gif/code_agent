cmake_minimum_required(VERSION 3.16)
project(R01PocoPostgreSQL LANGUAGES CXX)

enable_testing()

add_library(PocoDataPostgreSQL INTERFACE)
target_link_libraries(PocoDataPostgreSQL INTERFACE PostgreSQL::client)
target_include_directories(PocoDataPostgreSQL INTERFACE include)

add_executable(app src/main.cpp)
target_link_libraries(app PRIVATE PocoDataPostgreSQL)
add_test(NAME app_runs COMMAND app)
