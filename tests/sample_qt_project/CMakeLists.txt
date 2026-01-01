cmake_minimum_required(VERSION 3.16)
project(SampleQtApp VERSION 1.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_AUTOMOC ON)
set(CMAKE_AUTORCC ON)
set(CMAKE_AUTOUIC ON)

find_package(Qt6 REQUIRED COMPONENTS Core Widgets)

add_executable(sample_app
    src/main.cpp
    src/widget.cpp
    src/widget.h
    src/utils.cpp
    src/utils.h
    src/data_processor.cpp
    src/data_processor.h
)

target_link_libraries(sample_app PRIVATE Qt6::Core Qt6::Widgets)
