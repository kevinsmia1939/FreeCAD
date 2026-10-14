# SPDX-License-Identifier: LGPL-2.1-or-later

add_test(
    NAME ImplicitNativeSmoke
    COMMAND $<TARGET_FILE:FreeCADMainCmd> ${CMAKE_CURRENT_SOURCE_DIR}/native_smoke.py
)

set_tests_properties(ImplicitNativeSmoke PROPERTIES
    PASS_REGULAR_EXPRESSION "native implicit smoke test passed"
    FAIL_REGULAR_EXPRESSION "Traceback|Exception while processing file"
)

add_test(
    NAME ImplicitNativeMeshSmoke
    COMMAND $<TARGET_FILE:FreeCADMainCmd> ${CMAKE_CURRENT_SOURCE_DIR}/mesh_smoke.py
)

set_tests_properties(ImplicitNativeMeshSmoke PROPERTIES
    PASS_REGULAR_EXPRESSION "native implicit mesh smoke test passed"
    FAIL_REGULAR_EXPRESSION "Traceback|Exception while processing file"
    TIMEOUT 120
)
