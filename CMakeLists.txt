cmake_minimum_required(VERSION 3.12)
project(pcb_tail_router LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

add_executable(pcb_tail_router src/main.cpp)
target_include_directories(pcb_tail_router PRIVATE include)

