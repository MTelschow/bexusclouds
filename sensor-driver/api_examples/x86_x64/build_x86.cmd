@echo off
setlocal

rem builds a cmake file located in the same directory into a subfolder called "build"

:parameters
set platform="x86"
set compiler="msvc"

if "%1"=="" (
	set buildType="release"
) else (
    if /i "%1%"=="debug" (
	set buildType="debug"
    ) else (
        if /i "%1%"=="release" (
			set buildType="release"
        ) else (
            echo [91mProvided build type "%1%" is not a valid option[0m
            exit /B 1
        )
    )
)
set buildPath="build\%platform%\%compiler%\%buildType%"

if exist "C:\Program Files (x86)\Microsoft Visual Studio\2019\BuildTools" (
	set buildToolPath="C:\Program Files (x86)\Microsoft Visual Studio\2019\BuildTools\VC\Auxiliary\Build\vcvarsall.bat"
) else (
	if exist "C:\Program Files (x86)\Microsoft Visual Studio\2019\Professional" (
		set buildToolPath="C:\Program Files (x86)\Microsoft Visual Studio\2019\Professional\VC\Auxiliary\Build\vcvarsall.bat"
	) else (    
	echo ERROR: Microsoft Visual Studio 2019 Build Tools / Professional not found.
		exit /b || goto:eof
	)
)

:main_script
set originalPath="%cd%"
call :createFolders
call :buildPlatform
exit /b || goto:eof

:createFolders
if not exist %buildPath% md %buildPath% && ^
exit /b || goto:eof

:buildPlatform
%buildToolPath% x86 && ^
cd %buildPath% && ^
cmake -DCMAKE_BUILD_TYPE=%buildType% -Wno-dev -G "NMake Makefiles" ./../../../../ && ^
nmake && ^
cd %originalPath% && ^
exit /b || goto:eof
