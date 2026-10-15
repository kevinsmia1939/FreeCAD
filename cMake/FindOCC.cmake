# Try to find OCC
# Once done this will define
#
# OCC_FOUND          - system has OCC - OpenCASCADE
# OCC_INCLUDE_DIR    - where the OCC include directory can be found
# OCC_LIBRARY_DIR    - where the OCC library directory can be found
# OCC_LIBRARIES      - Link this to use OCC
# OCC_OCAF_LIBRARIES - Link this to use OCC OCAF framework

set(FREECAD_OCCT_BUILD_DIR "" CACHE PATH
    "Explicit OCCT source build (strict imported targets; no system-library fallback)")

# An OCCT build-tree export is not its install-tree Config.cmake. The latter
# derives installation paths and must not redirect an experimental build into
# installed libraries. Keep this opt-in, so existing system-OCCT builds survive.
if (FREECAD_OCCT_BUILD_DIR)
    get_filename_component(_freecad_occt_build "${FREECAD_OCCT_BUILD_DIR}" ABSOLUTE)
    if (NOT EXISTS "${_freecad_occt_build}/OpenCASCADETargets.cmake"
        OR NOT EXISTS "${_freecad_occt_build}/include/opencascade/Standard_Version.hxx")
        message(FATAL_ERROR "Explicit OCCT source build is not configured: ${_freecad_occt_build}")
    endif ()
    include("${_freecad_occt_build}/OpenCASCADETargets.cmake")
    get_target_property(_occt_configs TKernel IMPORTED_CONFIGURATIONS)
    list(GET _occt_configs 0 _occt_config)
    get_target_property(_occt_kernel TKernel "IMPORTED_LOCATION_${_occt_config}")
    get_filename_component(OpenCASCADE_LIBRARY_DIR "${_occt_kernel}" DIRECTORY)
    set(OpenCASCADE_INCLUDE_DIR "${_freecad_occt_build}/include/opencascade")
    set(OpenCASCADE_FOUND TRUE)
# Otherwise retain normal installed-OCCT discovery.
elseif (NOT OCCT_CMAKE_FALLBACK)
    find_package(OpenCASCADE CONFIG QUIET)
    get_property(flags DIRECTORY PROPERTY COMPILE_DEFINITIONS)
    # OCCT 7.5 adds this define that causes hundreds of compiler warnings with Qt5.x, so remove it again
    list(FILTER flags EXCLUDE REGEX [[GL_GLEXT_LEGACY]])
    set_property(DIRECTORY PROPERTY COMPILE_DEFINITIONS ${flags})
endif ()
if (OpenCASCADE_FOUND)
    set(OCC_FOUND ${OpenCASCADE_FOUND})
    set(OCC_INCLUDE_DIR ${OpenCASCADE_INCLUDE_DIR})
    set(OCC_LIBRARY_DIR ${OpenCASCADE_LIBRARY_DIR})
    set(OCC_LIBRARIES ${OpenCASCADE_LIBRARIES})
    set(OCC_OCAF_LIBRARIES TKCAF TKXCAF)
else ()
    if (WIN32)
        if (CYGWIN OR MINGW)
            find_path(OCC_INCLUDE_DIR Standard_Version.hxx
                    /usr/include/opencascade
                    /usr/local/include/opencascade
                    /opt/opencascade/include
                    /opt/opencascade/inc
            )
            find_path(OCC_LIBRARY TKernel
                    /usr/lib
                    /usr/local/lib
                    /opt/opencascade/lib
            )
        else ()
            find_path(OCC_INCLUDE_DIR Standard_Version.hxx
                    "[HKEY_LOCAL_MACHINE\\SOFTWARE\\SIM\\OCC\\2;Installation Path]/include"
            )
            find_library(OCC_LIBRARY TKernel
                    "[HKEY_LOCAL_MACHINE\\SOFTWARE\\SIM\\OCC\\2;Installation Path]/lib"
            )
        endif ()
    else ()
        find_path(OCC_INCLUDE_DIR Standard_Version.hxx
                /usr/include/occt
                /usr/include/opencascade
                /usr/local/include/opencascade
                /opt/opencascade/include
                /opt/opencascade/inc
        )
        find_library(OCC_LIBRARY TKernel
                /usr/lib
                /usr/local/lib
                /opt/opencascade/lib
        )
    endif ()
    if (OCC_LIBRARY)
        get_filename_component(OCC_LIBRARY_DIR ${OCC_LIBRARY} PATH)
        if (NOT OCC_INCLUDE_DIR)
            find_path(OCC_INCLUDE_DIR Standard_Version.hxx
                    ${OCC_LIBRARY_DIR}/../inc
            )
        endif ()
    endif ()
endif ()

if (OCC_INCLUDE_DIR)
    file(STRINGS ${OCC_INCLUDE_DIR}/Standard_Version.hxx OCC_MAJOR
            REGEX "#define OCC_VERSION_MAJOR.*"
    )
    string(REGEX MATCH "[0-9]+" OCC_MAJOR ${OCC_MAJOR})
    file(STRINGS ${OCC_INCLUDE_DIR}/Standard_Version.hxx OCC_MINOR
            REGEX "#define OCC_VERSION_MINOR.*"
    )
    string(REGEX MATCH "[0-9]+" OCC_MINOR ${OCC_MINOR})
    file(STRINGS ${OCC_INCLUDE_DIR}/Standard_Version.hxx OCC_MAINT
            REGEX "#define OCC_VERSION_MAINTENANCE.*"
    )
    string(REGEX MATCH "[0-9]+" OCC_MAINT ${OCC_MAINT})

    set(OCC_VERSION_STRING "${OCC_MAJOR}.${OCC_MINOR}.${OCC_MAINT}")

    # OCC_VERSION_DEVELOPMENT is only defined for development builds (e.g. "dev", "beta", "rc1")
    file(STRINGS ${OCC_INCLUDE_DIR}/Standard_Version.hxx OCC_DEVELOPMENT
            REGEX "#define OCC_VERSION_DEVELOPMENT.*"
    )
    if (OCC_DEVELOPMENT)
        string(REGEX MATCH "\"([^\"]*)\"" _ "${OCC_DEVELOPMENT}")
        set(OCC_VERSION_DEVELOPMENT "${CMAKE_MATCH_1}")
    endif ()
endif ()

# handle the QUIETLY and REQUIRED arguments and set OCC_FOUND to TRUE if
# all listed variables are TRUE
include(FindPackageHandleStandardArgs)
find_package_handle_standard_args(OCC REQUIRED_VARS OCC_INCLUDE_DIR VERSION_VAR OCC_VERSION_STRING)

if (OCC_FOUND)
    set(OCC_LIBRARIES
            TKFillet
            TKMesh
            TKernel
            TKG2d
            TKG3d
            TKMath
            TKShHealing
            TKXSBase
            TKBool
            TKBO
            TKBRep
            TKTopAlgo
            TKGeomAlgo
            TKGeomBase
            TKOffset
            TKPrim
            TKHLR
            TKFeat
    )
    if (OCC_VERSION_STRING VERSION_GREATER_EQUAL 7.9.0)
        list(APPEND OCC_LIBRARIES TKExpress)
    endif ()

    set(OCC_OCAF_LIBRARIES
            TKBin
            TKBinL
            TKCAF
            TKXCAF
            TKLCAF
            TKVCAF
            TKCDF
            TKMeshVS
            TKService
            TKV3d
            TKRWMesh
    )

    if (OCC_VERSION_STRING VERSION_LESS 7.8.0)
        list(APPEND OCC_LIBRARIES TKIGES TKSTL TKSTEPBase TKSTEPAttr TKSTEP209 TKSTEP)
        list(APPEND OCC_OCAF_LIBRARIES TKXDESTEP TKXDEIGES)
    else ()
        list(APPEND OCC_LIBRARIES TKDESTEP TKDEIGES TKDEGLTF TKDESTL)
    endif ()
    if (FREECAD_OCCT_BUILD_DIR)
        set(_occt_missing_targets "")
        set(_occt_unbuilt_targets "")
        foreach (_occt_target IN LISTS OCC_LIBRARIES OCC_OCAF_LIBRARIES)
            if (NOT TARGET "${_occt_target}")
                list(APPEND _occt_missing_targets "${_occt_target}")
                continue()
            endif ()
            get_target_property(_occt_configs "${_occt_target}" IMPORTED_CONFIGURATIONS)
            list(GET _occt_configs 0 _occt_config)
            get_target_property(_occt_library "${_occt_target}" "IMPORTED_LOCATION_${_occt_config}")
            if (NOT EXISTS "${_occt_library}")
                list(APPEND _occt_unbuilt_targets "${_occt_target}")
            endif ()
        endforeach ()
        if (_occt_missing_targets OR _occt_unbuilt_targets)
            message(FATAL_ERROR
                "Explicit OCCT source build is not ready for FreeCAD.\n"
                "Toolkits not configured: ${_occt_missing_targets}\n"
                "Toolkits configured but not built: ${_occt_unbuilt_targets}\n"
                "Build the required OCCT modules/toolkits first. System-library fallback is forbidden.\n"
                "Use a separate FreeCAD migration build; do not replace the working OCCT 7 build.")
        endif ()
        message(STATUS "Using explicit OCCT build-tree targets only: ${_freecad_occt_build}")
    endif ()
    if (OCC_VERSION_DEVELOPMENT)
        message(STATUS "Found OpenCASCADE version: ${OCC_VERSION_STRING} (${OCC_VERSION_DEVELOPMENT})")
    else ()
        message(STATUS "Found OpenCASCADE version: ${OCC_VERSION_STRING}")
    endif ()
    message(STATUS "  OpenCASCADE include directory: ${OCC_INCLUDE_DIR}")
    message(STATUS "  OpenCASCADE shared libraries directory: ${OCC_LIBRARY_DIR}")
endif ()
