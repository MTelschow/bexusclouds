project(bmv080_example)
cmake_minimum_required(VERSION 3.10)

# Check platform
if("${CMAKE_SIZEOF_VOID_P}" STREQUAL "4")
    set(PLATFORM_NUM_BITS "32")
    set(PLATFORM "x86")
else()
    set(PLATFORM_NUM_BITS "64")
    set(PLATFORM "x64")
endif()

# Check compiler
if (CMAKE_CXX_COMPILER_ID STREQUAL "MSVC")
    set(COMPILER "msvc")
else()
     message(FATAL_ERROR "${CMAKE_CXX_COMPILER_ID} compiler is not supported on platform ${PLATFORM}")
endif()
message("Building for ${PLATFORM} platform")

# Check build type
string(TOLOWER ${CMAKE_BUILD_TYPE} BUILD_TYPE)
# Set build fixed type for dependencies (libraries)
set(DEP_BUILD_TYPE "release")

# Find paths
set(API_DIR                   ${PROJECT_SOURCE_DIR}/../../api)
set(API_LIB_DIR               ${API_DIR}/lib/${PLATFORM}/${COMPILER}/${DEP_BUILD_TYPE})
set(COMMON_DIR                ${PROJECT_SOURCE_DIR}/../_common)
set(COMBRIDGE_LIB_DIR         ${PROJECT_SOURCE_DIR}/dep/${PLATFORM}/${COMPILER}/${DEP_BUILD_TYPE})
set(ARTIFACTS_DIR             ${PROJECT_SOURCE_DIR}/bin/${PLATFORM}/${COMPILER}/${BUILD_TYPE})

# Add include directories
include_directories(          ${PROJECT_SOURCE_DIR}/inc
                              ${COMMON_DIR}/inc
                              ${API_DIR}/inc)
# Add source files            
set(SOURCE_FILES              ${PROJECT_SOURCE_DIR}/src/main.c
                              ${COMMON_DIR}/src/bmv080_example.c)

# Add library files
set(LIBRARY_FILES             ${COMBRIDGE_LIB_DIR}/combridge.lib
                              ${API_LIB_DIR}/bmv080.lib)
# Build application
add_executable(               ${PROJECT_NAME} ${SOURCE_FILES})
target_link_libraries(        ${PROJECT_NAME} ${LIBRARY_FILES})

# Copy project artifact
add_custom_command(TARGET ${PROJECT_NAME} POST_BUILD COMMAND ${CMAKE_COMMAND} -E 
                   copy ${PROJECT_BINARY_DIR}/${PROJECT_NAME}.exe ${ARTIFACTS_DIR})

if (${BUILD_TYPE} STREQUAL "debug")
    add_custom_command(TARGET ${PROJECT_NAME} POST_BUILD COMMAND ${CMAKE_COMMAND} -E 
                   copy ${PROJECT_BINARY_DIR}/${PROJECT_NAME}.pdb ${ARTIFACTS_DIR})
endif()

# Copy libraries
file(COPY ${COMBRIDGE_LIB_DIR}/combridge.dll  DESTINATION ${ARTIFACTS_DIR})
file(COPY ${API_LIB_DIR}/bmv080.dll           DESTINATION ${ARTIFACTS_DIR})
file(COPY ${API_LIB_DIR}/postProcessor.dll    DESTINATION ${ARTIFACTS_DIR})

if (PLATFORM STREQUAL "x64")
    file(COPY ${COMBRIDGE_LIB_DIR}/LibFT4222-${PLATFORM_NUM_BITS}.dll  DESTINATION ${ARTIFACTS_DIR})
else()
    file(COPY ${COMBRIDGE_LIB_DIR}/LibFT4222.dll                       DESTINATION ${ARTIFACTS_DIR})
endif()
