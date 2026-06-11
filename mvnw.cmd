@echo off
setlocal

set "BASE_DIR=%~dp0"
set "MVNW_MAVEN_VERSION=3.9.9"
set "MVNW_DIR=%BASE_DIR%.mvn\wrapper"
set "MVNW_APACHE_MAVEN=%MVNW_DIR%\apache-maven-%MVNW_MAVEN_VERSION%"
set "MVNW_MAVEN_EXE=%MVNW_APACHE_MAVEN%\bin\mvn.cmd"
set "MVNW_ZIP=%MVNW_DIR%\apache-maven-%MVNW_MAVEN_VERSION%-bin.zip"
set "MVNW_URL=https://archive.apache.org/dist/maven/maven-3/%MVNW_MAVEN_VERSION%/binaries/apache-maven-%MVNW_MAVEN_VERSION%-bin.zip"

if not exist "%MVNW_MAVEN_EXE%" (
  if not exist "%MVNW_DIR%" mkdir "%MVNW_DIR%"
  powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$ErrorActionPreference='Stop';" ^
    "$zip='%MVNW_ZIP%';" ^
    "$url='%MVNW_URL%';" ^
    "if (!(Test-Path $zip)) { Invoke-WebRequest -Uri $url -OutFile $zip };" ^
    "Expand-Archive -Path $zip -DestinationPath '%MVNW_DIR%' -Force"
)

if not exist "%MVNW_MAVEN_EXE%" (
  echo Maven Wrapper bootstrap failed: %MVNW_MAVEN_EXE% not found.
  exit /b 1
)

call "%MVNW_MAVEN_EXE%" %*
