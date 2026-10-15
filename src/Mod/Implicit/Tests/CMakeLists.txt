# SPDX-License-Identifier: LGPL-2.1-or-later

foreach(query_test ray geometry)
    add_test(NAME Implicit${query_test}Smoke
        COMMAND $<TARGET_FILE:FreeCADMainCmd> ${CMAKE_CURRENT_SOURCE_DIR}/${query_test}_smoke.py)
    set_tests_properties(Implicit${query_test}Smoke PROPERTIES
        PASS_REGULAR_EXPRESSION "native implicit ${query_test} smoke test passed"
        FAIL_REGULAR_EXPRESSION "Traceback|Exception while processing file" TIMEOUT 120)
endforeach()

add_test(NAME ImplicitLinkedSmoke
    COMMAND $<TARGET_FILE:FreeCADMainCmd> ${CMAKE_CURRENT_SOURCE_DIR}/linked_smoke.py)
set_tests_properties(ImplicitLinkedSmoke PROPERTIES
    PASS_REGULAR_EXPRESSION "native implicit linked smoke test passed"
    FAIL_REGULAR_EXPRESSION "Traceback|Exception while processing file" TIMEOUT 120)

add_test(NAME ImplicitCancellationSmoke
    COMMAND $<TARGET_FILE:FreeCADMainCmd> ${CMAKE_CURRENT_SOURCE_DIR}/cancellation_smoke.py)
set_tests_properties(ImplicitCancellationSmoke PROPERTIES
    PASS_REGULAR_EXPRESSION "native implicit cancellation smoke test passed"
    FAIL_REGULAR_EXPRESSION "Traceback|Exception while processing file" TIMEOUT 120)

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
