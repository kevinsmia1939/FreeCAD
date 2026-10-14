# SPDX-License-Identifier: LGPL-2.1-or-later

set(Implicit_LIBS FreeCADApp)

set(Implicit_SRCS
    AppImplicit.cpp
    Feature.cpp
    Feature.h
    Field.cpp
    Field.h
    FieldGraph.cpp
    FieldGraph.h
    Shape.cpp
    Shape.h
    SurfaceMesh.cpp
    SurfaceMesh.h
)

add_library(Implicit SHARED ${Implicit_SRCS})

target_include_directories(Implicit PRIVATE
    ${CMAKE_BINARY_DIR}
    ${CMAKE_BINARY_DIR}/src
    ${CMAKE_SOURCE_DIR}/src
    ${CMAKE_CURRENT_BINARY_DIR}
)

target_include_directories(Implicit SYSTEM PRIVATE ${nlohmann_json_INCLUDE_DIRS})

target_link_libraries(Implicit ${Implicit_LIBS})
target_compile_warn_error(Implicit)

set_bin_dir(Implicit)
set_python_prefix_suffix(Implicit)

install(TARGETS Implicit DESTINATION ${CMAKE_INSTALL_LIBDIR})
