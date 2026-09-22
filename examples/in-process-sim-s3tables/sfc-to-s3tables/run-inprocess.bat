@echo off
rem Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
rem SPDX-License-Identifier: Apache-2.0
rem
rem Windows counterpart of run-inprocess.sh. Runs the SFC simulator-to-S3-Tables pipeline, sourcing the
rem modules from whichever is available:
rem
rem   1. SFC_MODULES_DIR, if you set it
rem   2. build\distribution -- a build of this working copy wins, so local changes are what run
rem   3. .\modules -- release bundles, downloaded here on first use
rem
rem Windows 10 and later ship curl and tar, which is all the download path needs; unlike run-inprocess.sh
rem there is no wget or jq dependency, because the release tag is parsed with plain cmd string ops.
rem
rem SFC is started with a direct `java -cp` rather than through bin\sfc-main.bat. The generated
rem launchers build the whole classpath into one `set CLASSPATH=` line, and cmd.exe caps a line at
rem 8191 characters -- sfc-main.bat is already 6060, and aws-s3-tables-target.bat is 11798 and so
rem cannot run at all. Passing lib\* lets the JVM expand the classpath instead, which has no such
rem limit.

setlocal enabledelayedexpansion

set "HERE=%~dp0"
if "%HERE:~-1%"=="\" set "HERE=%HERE:~0,-1%"

rem The modules this example needs: the core, a stand-in for a machine, the Iceberg target, and the
rem console target that "#DEBUGTarget" in the config enables.
set "SFC_REQUIRED_MODULES=sfc-main simulator aws-s3-tables-target debug-target"

set "REPO=https://github.com/awslabs/industrial-shopfloor-connect"
set "CONFIG=%HERE%\simulator-to-s3tables.json"

rem Give up rather than hang when there is no route to GitHub.
set "CURL_TIMEOUT=20"

rem ---------------------------------------------------------------------------------- prerequisites

rem sfc-main is a JVM process, so java is needed whichever source the modules come from.
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

rem Region for the AWS-S3-TABLES target. The config file reads it as ${AWS_REGION}, and sfc-main
rem aborts with "Placeholder ... could not be replaced" if it is unset. Deploy the cdk\ query app
rem into the same region -- DuckDB derives the S3 Tables endpoint from the table bucket's region.
if not defined AWS_REGION set "AWS_REGION=us-west-2"
echo Using AWS_REGION=%AWS_REGION%

rem ----------------------------------------------------------------------------------------- modules

for %%i in ("%HERE%\..\..\..") do set "REPO_ROOT=%%~fi"
set "BUILD_DIST=%REPO_ROOT%\build\distribution"
set "DOWNLOADED=%HERE%\modules"

if defined SFC_MODULES_DIR (
    echo Using SFC_MODULES_DIR from the environment: %SFC_MODULES_DIR%
    goto :run
)

call :have_all_bundles "%BUILD_DIST%"
if not errorlevel 1 (
    echo Using the local build: %BUILD_DIST%
    call :extract_missing "%BUILD_DIST%" || exit /b 1
    set "SFC_MODULES_DIR=%BUILD_DIST%"
    goto :run
)

call :have_all_bundles "%DOWNLOADED%"
if errorlevel 1 (
    call :download_modules || exit /b 1
)
echo Using the downloaded release bundles: %DOWNLOADED%
call :extract_missing "%DOWNLOADED%" || exit /b 1
set "SFC_MODULES_DIR=%DOWNLOADED%"

rem --------------------------------------------------------------------------------------------- run

:run
if not exist "%SFC_MODULES_DIR%\sfc-main\lib\" (
    echo No sfc-main libraries at %SFC_MODULES_DIR%\sfc-main\lib >&2
    exit /b 1
)

rem lib\* is a JVM classpath wildcard, expanded by java itself, not by cmd. The adapters and targets
rem are loaded at runtime from the JarFiles paths in the config, so only sfc-main is needed here.
echo Running com.amazonaws.sfc.MainController from %SFC_MODULES_DIR%\sfc-main\lib
java -cp "%SFC_MODULES_DIR%\sfc-main\lib\*" com.amazonaws.sfc.MainController -config "%CONFIG%"
exit /b %errorlevel%

rem ------------------------------------------------------------------------------------ subroutines

rem Sets errorlevel 1 unless every required module is present, either unpacked or still archived.
:have_all_bundles
for %%m in (%SFC_REQUIRED_MODULES%) do (
    if not exist "%~1\%%m\" if not exist "%~1\%%m.tar.gz" exit /b 1
)
exit /b 0

rem `gradlew build` leaves tar.gz bundles next to any it has already unpacked, so extract whatever is
rem still archived. Skipped when the directory is already there, which keeps reruns quick.
:extract_missing
where tar >nul 2>&1
if errorlevel 1 (
    echo Missing prerequisite for unpacking modules: tar >&2
    echo   tar  ships with Windows 10 and later >&2
    exit /b 1
)
for %%m in (%SFC_REQUIRED_MODULES%) do (
    if not exist "%~1\%%m\" (
        echo   extracting %%m
        tar -xf "%~1\%%m.tar.gz" -C "%~1"
        if errorlevel 1 exit /b 1
    )
)
exit /b 0

rem Fetch the precompiled bundles for the latest release. One URL per module rather than a loop over
rem a brace expansion, so a failure names the module that could not be downloaded.
:download_modules
where curl >nul 2>&1
if errorlevel 1 (
    echo Missing prerequisite for downloading the release bundles: curl >&2
    echo   curl  ships with Windows 10 and later, and is used to resolve the tag and fetch the bundles >&2
    echo   Alternatively build from source: gradlew build in the repository root, which >&2
    echo   run-inprocess.bat prefers over the downloads anyway. >&2
    exit /b 1
)

if not defined VERSION call :latest_tag
if not defined VERSION (
    echo Could not resolve the latest release tag from GitHub. >&2
    echo   Check network access, or set VERSION=vX.Y.Z and retry. >&2
    exit /b 1
)

echo Downloading SFC modules for %VERSION% into %DOWNLOADED%
if not exist "%DOWNLOADED%" mkdir "%DOWNLOADED%"
for %%m in (%SFC_REQUIRED_MODULES%) do (
    if not exist "%DOWNLOADED%\%%m\" (
        echo   %%m
        curl -fL --progress-bar -o "%DOWNLOADED%\%%m.tar.gz" "%REPO%/releases/download/%VERSION%/%%m.tar.gz"
        if errorlevel 1 (
            del /q "%DOWNLOADED%\%%m.tar.gz" 2>nul
            echo Could not download %%m for %VERSION%. >&2
            exit /b 1
        )
        tar -xf "%DOWNLOADED%\%%m.tar.gz" -C "%DOWNLOADED%"
        if errorlevel 1 exit /b 1
        del /q "%DOWNLOADED%\%%m.tar.gz"
    )
)
exit /b 0

rem Reads the newest tag out of the GitHub API response. The tags endpoint lists newest first and
rem carries exactly one "name" per tag -- and no other field contains that word -- so the first match
rem is the one wanted. Parsed with cmd string replacement instead of jq, which does not ship with Windows.
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
