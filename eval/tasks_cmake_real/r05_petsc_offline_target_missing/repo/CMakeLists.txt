cmake_minimum_required(VERSION 3.16)
project(R05PetscOffline LANGUAGES CXX)

enable_testing()

find_package(PkgConfig REQUIRED)
pkg_check_modules(PETSC REQUIRED IMPORTED_TARGET PETSc)

add_executable(app src/main.cpp)
target_link_libraries(app PRIVATE PkgConfig::PETSC)
add_test(NAME app_runs COMMAND app)
