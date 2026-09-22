@echo off
rem Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
rem SPDX-License-Identifier: Apache-2.0
rem
rem Windows counterpart of run-uberjar.sh. Runs either direction of this example straight out of the
rem uberjar:
rem
rem   run-uberjar.bat server   -- sim-to-opcua.json:   SFC serves OPC UA on port 4841
rem   run-uberjar.bat client   -- umati-to-debug.json: SFC reads the umati server on port 4840
rem
rem The point of this example is the uberjar invocation itself: a single `java -jar`, and configs with
rem no JarFiles entries, because every adapter and target is already on the jar's own classpath.
rem
rem The bundle is sourced from whichever is available:
rem
rem   1. SFC_UBERJAR_DIR, if you set it (the directory that CONTAINS sfc-uberjar\)
rem   2. build\distribution -- a build of this working copy wins, so local changes are what run
rem   3. .\uberjar -- the release bundle, downloaded here on first use
rem
rem Running only ever needs java; curl is needed solely for that third case. Windows 10 and later
rem ship both curl and tar, so unlike run-uberjar.sh there is no wget or jq dependency.
rem
rem SFC is started with a direct `java -jar` rather than through bin\sfc-uberjar.bat, because the
rem generated launchers build the whole classpath into one `set CLASSPATH=` line and cmd.exe caps a
rem line at 8191 characters.

setlocal enabledelayedexpansion

set "HERE=%~dp0"
if "%HERE:~-1%"=="\" set "HERE=%HERE:~0,-1%"

set "REPO=https://github.com/awslabs/industrial-shopfloor-connect"
set "BUNDLE=sfc-uberjar.tar.gz"

rem Give up rather than hang when there is no route to GitHub.
set "CURL_TIMEOUT=20"

rem ------------------------------------------------------------------------------- which config

set "MODE=%~1"
if /i "%MODE%"=="server" (
    set "CONFIG=%HERE%\sim-to-opcua.json"
) else if /i "%MODE%"=="client" (
    set "CONFIG=%HERE%\umati-to-debug.json"
) else (
    echo Usage: run-uberjar.bat ^<server^|client^> [extra sfc args...] >&2
    echo. >&2
    echo   server   sim-to-opcua.json    SFC exposes simulated signals as an OPC UA server on port 4841 >&2
    echo   client   umati-to-debug.json  SFC reads the umati sample server on port 4840 to the debug target >&2
    echo. >&2
    echo Anything after the mode is passed through to SFC, e.g. run-uberjar.bat client -trace >&2
    exit /b 1
)
rem Drop the mode, so %* below carries only the pass-through arguments.
shift

rem --------------------------------------------------------------------------------- prerequisites

where java >nul 2>&1
if errorlevel 1 (
    echo Missing prerequisite for running SFC: java >&2
    echo   java  a Java 17+ runtime, e.g. 'winget install EclipseAdoptium.Temurin.17.JDK' >&2
    exit /b 1
)
for /f "tokens=*" %%v in ('java -version 2^>^&1') do (
    if not defined JAVA_BANNER set "JAVA_BANNER=%%v"
)
echo Using %JAVA_BANNER%

rem The client config connects to opc.tcp://localhost:4840, which is the umati sample server rather
rem than anything SFC starts. Say so up front instead of letting it fail as a connection timeout.
if /i "%MODE%"=="client" (
    netstat -an | findstr /c:":4840 " | findstr /i LISTENING >nul 2>&1
    if errorlevel 1 (
        echo Nothing is listening on port 4840. Start the umati sample server first: >&2
        echo   docker run -d -p 4840:4840 ghcr.io/umati/sample-server:main >&2
        exit /b 1
    )
)

rem ------------------------------------------------------------------------------------- the bundle

for %%i in ("%HERE%\..\..") do set "REPO_ROOT=%%~fi"
set "BUILD_DIST=%REPO_ROOT%\build\distribution"
set "DOWNLOADED=%HERE%\uberjar"

if defined SFC_UBERJAR_DIR (
    echo Using SFC_UBERJAR_DIR from the environment: %SFC_UBERJAR_DIR%
    goto :run
)

call :have_bundle "%BUILD_DIST%"
if not errorlevel 1 (
    echo Using the local build: %BUILD_DIST%
    call :extract_missing "%BUILD_DIST%" || exit /b 1
    set "SFC_UBERJAR_DIR=%BUILD_DIST%"
    goto :run
)

call :have_bundle "%DOWNLOADED%"
if errorlevel 1 (
    call :download_bundle || exit /b 1
)
echo Using the downloaded release bundle: %DOWNLOADED%
call :extract_missing "%DOWNLOADED%" || exit /b 1
set "SFC_UBERJAR_DIR=%DOWNLOADED%"

rem --------------------------------------------------------------------------------------------- run

:run
rem The version is part of the filename, so resolve it rather than hardcoding it.
set "UBERJAR="
for %%j in ("%SFC_UBERJAR_DIR%\sfc-uberjar\lib\sfc-uberjar-*.jar") do set "UBERJAR=%%~fj"
if not defined UBERJAR (
    echo No sfc-uberjar-^<version^>.jar under %SFC_UBERJAR_DIR%\sfc-uberjar\lib >&2
    exit /b 1
)

rem Default to -info, but only when the caller has not chosen a level themselves -- passing both
rem would leave which one wins up to argument order.
set "LEVEL=-info"
for %%a in (%*) do (
    if /i "%%a"=="-trace"   set "LEVEL="
    if /i "%%a"=="-info"    set "LEVEL="
    if /i "%%a"=="-warning" set "LEVEL="
    if /i "%%a"=="-error"   set "LEVEL="
)

rem One jar, one config, no JarFiles -- that is the whole uberjar story.
echo Running %UBERJAR% with %CONFIG%
java -jar "%UBERJAR%" -config "%CONFIG%" %LEVEL% %*
exit /b %errorlevel%

rem ------------------------------------------------------------------------------------ subroutines

rem Present either already unpacked, or still as the tarball `gradlew build` produced.
:have_bundle
if exist "%~1\sfc-uberjar\" exit /b 0
if exist "%~1\%BUNDLE%" exit /b 0
exit /b 1

rem Skipped when the directory is already there, which keeps reruns quick.
:extract_missing
if exist "%~1\sfc-uberjar\" exit /b 0
where tar >nul 2>&1
if errorlevel 1 (
    echo Missing prerequisite for unpacking the uberjar bundle: tar >&2
    echo   tar  ships with Windows 10 and later >&2
    exit /b 1
)
echo   extracting sfc-uberjar
tar -xf "%~1\%BUNDLE%" -C "%~1"
exit /b %errorlevel%

:download_bundle
where curl >nul 2>&1
if errorlevel 1 (
    echo Missing prerequisite for downloading the release bundle: curl >&2
    echo   curl  ships with Windows 10 and later, and is used to resolve the tag and fetch the bundle >&2
    echo   Alternatively build from source: gradlew build in the repository root, which >&2
    echo   run-uberjar.bat prefers over the download anyway. >&2
    exit /b 1
)

if not defined VERSION call :latest_tag
if not defined VERSION (
    echo Could not resolve the latest release tag from GitHub. >&2
    echo   Check network access, or set VERSION=vX.Y.Z and retry. >&2
    exit /b 1
)

rem The bundle is a few hundred MB, since it carries every adapter and target.
echo Downloading the SFC uberjar for %VERSION% into %DOWNLOADED%
if not exist "%DOWNLOADED%" mkdir "%DOWNLOADED%"
curl -fL --progress-bar -o "%DOWNLOADED%\%BUNDLE%" "%REPO%/releases/download/%VERSION%/%BUNDLE%"
if errorlevel 1 (
    del /q "%DOWNLOADED%\%BUNDLE%" 2>nul
    echo Could not download %BUNDLE% for %VERSION%. >&2
    exit /b 1
)
tar -xf "%DOWNLOADED%\%BUNDLE%" -C "%DOWNLOADED%"
if errorlevel 1 exit /b 1
del /q "%DOWNLOADED%\%BUNDLE%"
exit /b 0

rem Reads the newest tag out of the GitHub API response. The tags endpoint lists newest first and
rem carries exactly one "name" per tag -- and no other field contains that word -- so the first match
rem is the one wanted. Parsed with cmd string replacement instead of jq, which is not on Windows.
:latest_tag
set "RAWTAG="
for /f "usebackq tokens=2 delims=:" %%a in (`curl -fsSL --max-time %CURL_TIMEOUT% "https://api.github.com/repos/awslabs/industrial-shopfloor-connect/tags" ^| findstr name`) do (
    if not defined RAWTAG set "RAWTAG=%%a"
)
if not defined RAWTAG exit /b 0
set "RAWTAG=%RAWTAG: =%"
set "RAWTAG=%RAWTAG:"=%"
set "RAWTAG=%RAWTAG:,=%"
if not "%RAWTAG%"=="" set "VERSION=%RAWTAG%"
exit /b 0
