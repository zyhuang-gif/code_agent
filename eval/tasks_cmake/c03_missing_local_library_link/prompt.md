Fix the CMake build. A local library target exists and should be linked into the executable.
Use target_link_libraries rather than copying source files into the executable.
