@echo off
rem Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
rem SPDX-License-Identifier: Apache-2.0
rem
rem Windows counterpart of run-uberjar.sh. Same pipeline as run-inprocess.bat, one artifact instead of four:
rem sfc-uberjar.tar.gz already contains the core, every adapter and every target, so
rem simulator-to-s3tables-uberjar.json names its components by FactoryClassName alone and needs no
rem JarFiles paths.
rem
rem The bundle is sourced from whichever is available:
rem
rem   1. SFC_UBERJAR_DIR, if you set it (the directory that CONTAINS sfc-uberjar\)
rem   2. build\distribution -- a build of this working copy wins, so local changes are what run
rem   3. .\uberjar -- the release bundle, downloaded here on first use
rem
rem Running only ever needs java; curl is needed solely for that third case, so it is checked at the
rem point of download rather than up front. Windows 10 and later ship both curl and tar, so unlike
rem run-uberjar.sh there is no wget or jq dependency.
rem
rem SFC is started with a direct `java -jar` rather than through bin\sfc-uberjar.bat. The generated
rem launchers build the whole classpath into one `set CLASSPATH=` line, and cmd.exe caps a line at
rem 8191 characters -- aws-s3-tables-target.bat is already 11798 and cannot run at all. Invoking the
rem JVM ourselves keeps that limit out of the picture.

setlocal enabledelayedexpansion

set "HERE=%~dp0"
if "%HERE:~-1%"=="\" set "HERE=%HERE:~0,-1%"

set "REPO=https://github.com/awslabs/industrial-shopfloor-connect"
set "BUNDLE=sfc-uberjar.tar.gz"
set "CONFIG=%HERE%\simulator-to-s3tables-uberjar.json"

rem Give up rather than hang when there is no route to GitHub.
set "CURL_TIMEOUT=20"

rem ---------------------------------------------------------------------------------- prerequisites

rem SFC is a JVM process, so java is needed whichever source the bundle comes from.
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

rem Region for the AWS-S3-TABLES target. The config file reads it as ${AWS_REGION}, and SFC aborts
rem with "Placeholder ... could not be replaced" if it is unset. Deploy the cdk\ query app into the
rem same region -- DuckDB derives the S3 Tables endpoint from the table bucket's region.
if not defined AWS_REGION set "AWS_REGION=us-west-2"
echo Using AWS_REGION=%AWS_REGION%

rem ------------------------------------------------------------------------------------- the bundle

for %%i in ("%HERE%\..\..\..") do set "REPO_ROOT=%%~fi"
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

rem The fat jar declares Main-Class: com.amazonaws.sfc.MainController, so -jar is enough; it also
rem carries every dependency, so there is no classpath to assemble.
echo Running %UBERJAR%
java -jar "%UBERJAR%" -config "%CONFIG%"
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
