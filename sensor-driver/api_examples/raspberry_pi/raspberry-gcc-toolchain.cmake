# Reference for this tool-chain file: https://github.com/vpetrigo/arm-cmake-toolchains

set(CMAKE_SYSTEM_NAME Linux)
set(CMAKE_SYSTEM_PROCESSOR ARM)

if(MINGW OR CYGWIN OR WIN32)
    set(UTIL_SEARCH_CMD where)
elseif(UNIX OR APPLE)
    set(UTIL_SEARCH_CMD which)
endif()

if(BUILD_32)
    set(TOOLCHAIN_PREFIX arm-linux-gnueabihf-)
else()
    set(TOOLCHAIN_PREFIX aarch64-linux-gnu-)
endif()

set(ARCH "armv6" CACHE STRING "ARM architecture (instruction set) for Raspberry Pi")

execute_process(
    COMMAND ${UTIL_SEARCH_CMD} ${TOOLCHAIN_PREFIX}gcc
    OUTPUT_VARIABLE BINUTILS_PATH
    OUTPUT_STRIP_TRAILING_WHITESPACE)

get_filename_component(ARM_TOOLCHAIN_DIR ${BINUTILS_PATH} DIRECTORY)
# This flag is required for CMake to pass its compilation checks
if (${CMAKE_VERSION} VERSION_EQUAL "3.6.0" OR ${CMAKE_VERSION} VERSION_GREATER "3.6")
    set(CMAKE_TRY_COMPILE_TARGET_TYPE STATIC_LIBRARY)
else()
    set(CMAKE_EXE_LINKER_FLAGS_INIT "--specs=nosys.specs")
endif()

set(COMMON_FLAGS "-march=${ARCH}")

set(CMAKE_C_COMPILER    ${TOOLCHAIN_PREFIX}gcc)
set(CMAKE_LINKER        ${TOOLCHAIN_PREFIX}ld)
set(CMAKE_CXX_COMPILER  ${TOOLCHAIN_PREFIX}g++)

set(CMAKE_OBJCOPY       ${ARM_TOOLCHAIN_DIR}/${TOOLCHAIN_PREFIX}objcopy CACHE INTERNAL "objcopy tool")
set(CMAKE_SIZE_UTIL     ${ARM_TOOLCHAIN_DIR}/${TOOLCHAIN_PREFIX}size    CACHE INTERNAL "size tool")

set(CMAKE_FIND_ROOT_PATH ${ARM_TOOLCHAIN_DIR})
set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
