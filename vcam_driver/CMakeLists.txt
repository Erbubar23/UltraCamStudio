cmake_minimum_required(VERSION 3.20)
project(UltraCamVirtualCamera VERSION 1.0.0 LANGUAGES CXX RC)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
# CRT estático: la DLL se carga dentro de Zoom, Teams, OBS…, que no tienen por
# qué traer el runtime de Visual C++ que usamos al compilar.
set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")

if(CMAKE_SIZEOF_VOID_P EQUAL 8)
    set(ULTRACAM_ARCH 64)
else()
    set(ULTRACAM_ARCH 32)
endif()

# ---- Clases base de DirectShow (Microsoft, MIT; vía Softcam) ----
add_library(baseclasses STATIC
    third_party/baseclasses/amfilter.cpp
    third_party/baseclasses/amvideo.cpp
    third_party/baseclasses/combase.cpp
    third_party/baseclasses/dllentry.cpp
    third_party/baseclasses/dllsetup.cpp
    third_party/baseclasses/mtype.cpp
    third_party/baseclasses/source.cpp
    third_party/baseclasses/winutil.cpp
    third_party/baseclasses/wxdebug.cpp
    third_party/baseclasses/wxlist.cpp
    third_party/baseclasses/wxutil.cpp
)
target_include_directories(baseclasses PUBLIC third_party/baseclasses)
target_compile_definitions(baseclasses PUBLIC WIN32 UNICODE _UNICODE _CRT_SECURE_NO_WARNINGS)
target_compile_options(baseclasses PRIVATE /W3 /wd4996)
target_link_libraries(baseclasses PUBLIC strmiids winmm)

# ---- Driver ----
set(ULTRACAM_ICON "${CMAKE_CURRENT_SOURCE_DIR}/../assets/app.ico")
string(REPLACE "." "," ULTRACAM_VERSION_COMMA "${PROJECT_VERSION}.0")
configure_file(src/ultracam-vcam.rc.in ${CMAKE_CURRENT_BINARY_DIR}/ultracam-vcam.rc @ONLY)

add_library(ultracam-vcam SHARED
    src/dllmain.cpp
    src/UltraCamFilter.cpp
    src/SharedFrames.cpp
    src/Slate.cpp
    src/Convert.cpp
    src/ultracam-vcam.def
    ${CMAKE_CURRENT_BINARY_DIR}/ultracam-vcam.rc
)
set_target_properties(ultracam-vcam PROPERTIES OUTPUT_NAME "ultracam-vcam${ULTRACAM_ARCH}")
# /utf-8: el código está en UTF-8 (tildes y eñes de los carteles)
target_compile_options(ultracam-vcam PRIVATE /W4 /permissive- /wd4100 $<$<COMPILE_LANGUAGE:CXX>:/utf-8>)
target_link_libraries(ultracam-vcam PRIVATE baseclasses ole32 oleaut32 uuid gdi32 user32 advapi32)

# ---- Herramienta de prueba: abre la cámara como un programa cualquiera (tests/) ----
add_executable(vcam_probe tests/probe/probe.cpp)
set_target_properties(vcam_probe PROPERTIES OUTPUT_NAME "vcam_probe${ULTRACAM_ARCH}")
target_compile_definitions(vcam_probe PRIVATE UNICODE _UNICODE)
target_link_libraries(vcam_probe PRIVATE strmiids ole32 oleaut32 uuid)
