# SPDX-License-Identifier: LGPL-2.1-or-later
add_library(ImplicitGui SHARED AppImplicitGui.cpp ViewProviderShape.cpp ViewProviderShape.h)
target_include_directories(ImplicitGui PRIVATE ${CMAKE_BINARY_DIR} ${CMAKE_BINARY_DIR}/src
    ${CMAKE_SOURCE_DIR}/src ${CMAKE_CURRENT_BINARY_DIR})
target_link_libraries(ImplicitGui Implicit FreeCADGui ${QtConcurrent_LIBRARIES})
target_compile_warn_error(ImplicitGui)
set_bin_dir(ImplicitGui)
set_python_prefix_suffix(ImplicitGui)
fc_target_copy_resource_flat(ImplicitGui ${CMAKE_CURRENT_SOURCE_DIR}
    ${CMAKE_BINARY_DIR}/Mod/Implicit ../InitGui.py)
install(TARGETS ImplicitGui DESTINATION ${CMAKE_INSTALL_LIBDIR})
install(FILES ../InitGui.py DESTINATION Mod/Implicit)
