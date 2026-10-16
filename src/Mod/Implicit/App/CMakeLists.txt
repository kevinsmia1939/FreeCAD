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

# Never build/load native OCCT 8 face code against the OCCT 7 compatibility ABI.
if(FREECAD_OCCT_BUILD_DIR AND OCC_VERSION_STRING VERSION_GREATER_EQUAL 8.0.0)
    target_sources(Implicit PRIVATE NativeGeometry.h NativeGeometry.cpp)
    target_compile_definitions(Implicit PRIVATE IMPLICIT_WITH_NATIVE_GEOMETRY)
    target_include_directories(Implicit SYSTEM PRIVATE ${OCC_INCLUDE_DIR})
    target_link_libraries(Implicit TKTopAlgo)
    if(NOT EXISTS "${OCC_INCLUDE_DIR}/BRep_ImplicitTool.hxx")
        message(FATAL_ERROR "Selected OCCT build lacks native implicit faces")
    endif()
    add_library(_ImplicitOCCT SHARED AppNativeOCCT.cpp)
    target_include_directories(_ImplicitOCCT SYSTEM PRIVATE ${OCC_INCLUDE_DIR})
    target_link_libraries(_ImplicitOCCT PRIVATE TKTopAlgo TKMesh Python3::Python)
    target_compile_warn_error(_ImplicitOCCT)
    set_bin_dir(_ImplicitOCCT)
    set_python_prefix_suffix(_ImplicitOCCT)
    add_dependencies(Implicit _ImplicitOCCT)
    install(TARGETS _ImplicitOCCT DESTINATION ${CMAKE_INSTALL_LIBDIR})
endif()

# Use the fork's kernel implementation in a native source build. Compatibility
# builds compile only the new extension against installed OCCT, without mixing
# the fork's general headers into an older OCCT ABI.
set(IMPLICIT_OCCT_SOURCE_DIR "" CACHE PATH "OCCT fork source with signed-distance extension")
if(IMPLICIT_OCCT_SOURCE_DIR)
    set(_implicit_occt_dir "${IMPLICIT_OCCT_SOURCE_DIR}/src/ModelingAlgorithms/TKTopAlgo/BRepClass3d")
    if(NOT EXISTS "${_implicit_occt_dir}/BRepClass3d_SignedDistance.cxx")
        message(FATAL_ERROR "OCCT fork signed-distance source missing")
    endif()
    target_sources(Implicit PRIVATE BRepField.cpp BRepField.h)
    if(FREECAD_OCCT_BUILD_DIR)
        if(NOT EXISTS "${OCC_INCLUDE_DIR}/BRepClass3d_SignedDistance.hxx")
            message(FATAL_ERROR "Selected OCCT build lacks the fork's signed-distance extension")
        endif()
    else()
        target_sources(Implicit PRIVATE "${_implicit_occt_dir}/BRepClass3d_SignedDistance.cxx")
        configure_file("${_implicit_occt_dir}/BRepClass3d_SignedDistance.hxx"
            "${CMAKE_CURRENT_BINARY_DIR}/occt-implicit-include/BRepClass3d_SignedDistance.hxx" COPYONLY)
        target_include_directories(Implicit PRIVATE "${CMAKE_CURRENT_BINARY_DIR}/occt-implicit-include")
    endif()
    target_include_directories(Implicit SYSTEM PRIVATE ${OCC_INCLUDE_DIR})
    target_link_directories(Implicit PRIVATE ${OCC_LIBRARY_DIR})
    target_link_libraries(Implicit ${OCC_LIBRARIES})
    target_compile_definitions(Implicit PRIVATE IMPLICIT_WITH_OCCT_BRIDGE)
    if(BUILD_PART)
        target_link_libraries(Implicit Part)
        target_compile_definitions(Implicit PRIVATE IMPLICIT_WITH_PART_BRIDGE)
    endif()
endif()

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
