# SPDX-License-Identifier: LGPL-2.1-or-later

add_subdirectory(App)

if(BUILD_GUI)
    add_subdirectory(Gui)
endif()

if(ENABLE_DEVELOPER_TESTS)
    add_subdirectory(Tests)
endif()

set(Implicit_Scripts Init.py ImplicitCommands.py ImplicitPatch.py ImplicitNative.py)

add_custom_target(ImplicitScripts ALL SOURCES ${Implicit_Scripts})

fc_target_copy_resource(ImplicitScripts
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${CMAKE_BINARY_DIR}/Mod/Implicit
    ${Implicit_Scripts})

install(FILES ${Implicit_Scripts} DESTINATION Mod/Implicit)
