# SPDX-License-Identifier: LGPL-2.1-or-later

add_subdirectory(App)

if(BUILD_GUI)
    add_subdirectory(Gui)
endif()

if(ENABLE_DEVELOPER_TESTS)
    add_subdirectory(Tests)
endif()

set(Implicit_Scripts Init.py ImplicitCommands.py ImplicitWorkbench.py ImplicitPatch.py ImplicitNative.py ImplicitSection.py ImplicitOCCT.py ImplicitMixed.py Resources/icons/ImplicitGyroid.svg)

add_custom_target(ImplicitScripts ALL SOURCES ${Implicit_Scripts})

fc_target_copy_resource(ImplicitScripts
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${CMAKE_BINARY_DIR}/Mod/Implicit
    ${Implicit_Scripts})

install(FILES Init.py ImplicitCommands.py ImplicitWorkbench.py ImplicitPatch.py ImplicitNative.py ImplicitSection.py ImplicitOCCT.py ImplicitMixed.py DESTINATION Mod/Implicit)
install(FILES Resources/icons/ImplicitGyroid.svg DESTINATION Mod/Implicit/Resources/icons)
