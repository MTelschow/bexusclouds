cmake_minimum_required(VERSION 3.10)
project(bmv080_example)

set(PLATFORM "raspberry_pi")
set(CMAKE_EXE_LINKER_FLAGS "-Wl,-rpath=$$ORIGIN")

message("Building for ${PLATFORM} platform")

# Check build type
string(TOLOWER ${CMAKE_BUILD_TYPE} BUILD_TYPE)
string(TOUPPER ${CMAKE_BUILD_TYPE} BUILD_TYPE_UPPER)

# Preprocessor definitions for communication interface selection
add_definitions(-DHOST_INTERFACE_SPI=1 -DHOST_INTERFACE_I2C=2)
add_definitions(-DHOST_INTERFACE=${HOST_INTERFACE})

# Find paths
set(API_DIR                   ${PROJECT_SOURCE_DIR}/../../api)
set(COMMON_DIR                ${PROJECT_SOURCE_DIR}/../_common)

# Set Artifacts directory
if(HOST_INTERFACE EQUAL 1) # SPI host interface
    set(ARTIFACTS_DIR             ${PROJECT_SOURCE_DIR}/bin/${ARCH}/${TOOLCHAIN_PREFIX}gcc/${BUILD_TYPE}_spi)
elseif(HOST_INTERFACE EQUAL 2) # I2C host interface
    set(ARTIFACTS_DIR             ${PROJECT_SOURCE_DIR}/bin/${ARCH}/${TOOLCHAIN_PREFIX}gcc/${BUILD_TYPE}_i2c)
else()
    set(ARTIFACTS_DIR             ${PROJECT_SOURCE_DIR}/bin/${ARCH}/${TOOLCHAIN_PREFIX}gcc/${BUILD_TYPE})
endif()

# Add include directories
include_directories(          ${PROJECT_SOURCE_DIR}/inc
                              ${COMMON_DIR}/inc
                              ${API_DIR}/inc)
# Add source files            
set(SOURCE_FILES              ${PROJECT_SOURCE_DIR}/src/main.cpp
                              ${PROJECT_SOURCE_DIR}/src/combridge.cpp
                              ${COMMON_DIR}/src/bmv080_example.c)

if(CMAKE_TOOLCHAIN_FILE)
    MESSAGE(STATUS "Using toolchain file: ${CMAKE_TOOLCHAIN_FILE}")
endif()

# Set optimization level to Os for a RELEASE build.
# COMMON_FLAGS is only used for the (embedded) platforms that use the GCC compiler
if (${BUILD_TYPE_UPPER} STREQUAL "RELEASE")
	set(COMMON_FLAGS "${COMMON_FLAGS} -Os")
endif()

# For all platforms that use the GCC compiler, define a common set of C and C++ build flags
if(CMAKE_CXX_COMPILER_ID MATCHES "GNU")
    set(ADDITIONAL_CXX_FLAGS    "-Wall -Wshadow")
    set(ADDITIONAL_C_FLAGS      "-ffunction-sections -fdata-sections -Wall -Wshadow -Wextra -Wundef -Wno-unused-parameter -Wstrict-prototypes -Wmissing-prototypes -Wno-stringop-truncation")

    set(CMAKE_CXX_FLAGS_${BUILD_TYPE_UPPER}  "${COMMON_FLAGS} ${ADDITIONAL_CXX_FLAGS} -std=c++17" CACHE INTERNAL "" FORCE)
    set(CMAKE_C_FLAGS_${BUILD_TYPE_UPPER}    "${COMMON_FLAGS} ${ADDITIONAL_C_FLAGS} -std=gnu11" CACHE INTERNAL "" FORCE)
endif()

set(LIBRARY_FILES             ${API_DIR}/lib/${PLATFORM}/${ARCH}/${TOOLCHAIN_PREFIX}gcc/${BUILD_TYPE}/lib_bmv080.so)
# Build application
add_executable(               ${PROJECT_NAME} ${SOURCE_FILES})
target_link_libraries(        ${PROJECT_NAME} ${LIBRARY_FILES})

# Copy project artifact


add_custom_command(TARGET ${PROJECT_NAME} POST_BUILD COMMAND ${CMAKE_COMMAND} -E copy ${PROJECT_BINARY_DIR}/${PROJECT_NAME}  ${ARTIFACTS_DIR})
file(COPY ${API_DIR}/lib/${PLATFORM}/${ARCH}/${TOOLCHAIN_PREFIX}gcc/${BUILD_TYPE}/lib_bmv080.so  DESTINATION ${ARTIFACTS_DIR})
file(COPY ${API_DIR}/lib/${PLATFORM}/${ARCH}/${TOOLCHAIN_PREFIX}gcc/${BUILD_TYPE}/lib_postProcessor.so   DESTINATION ${ARTIFACTS_DIR})
file(COPY ${PROJECT_SOURCE_DIR}/run_bmv080_example.sh   DESTINATION ${ARTIFACTS_DIR})
