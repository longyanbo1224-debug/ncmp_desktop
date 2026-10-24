@echo off
REM ===================================================================
REM  ncmp mobile - Android APK build script
REM
REM  NOTE: keep every message in this file ASCII-only, and use CRLF
REM  line endings (same reason as build.bat).
REM ===================================================================
chcp 65001 >nul
setlocal
cd /d "%~dp0"
REM gradlew.bat needs java on PATH or JAVA_HOME; the JDK check below uses PATH.
if defined JAVA_HOME set "PATH=%JAVA_HOME%\bin;%PATH%"

echo ============================================
echo   ncmp mobile - build
echo ============================================
echo.

REM ---------------------------------------------------------------
REM [1/4] Check Android SDK
REM ---------------------------------------------------------------
echo [1/4] Checking Android SDK ...
set HAVE_SDK=0
if exist "android\local.properties" set HAVE_SDK=1
if defined ANDROID_HOME set HAVE_SDK=1
if not "%HAVE_SDK%"=="1" (
    echo.
    echo   ERROR: Android SDK not found.
    echo   Set ANDROID_HOME, or create android\local.properties
    echo   containing:  sdk.dir=C:/path/to/Android/Sdk
    echo.
    if not defined NOPAUSE pause
    exit /b 1
)
echo     SDK found

REM ---------------------------------------------------------------
REM [2/4] Check JDK
REM ---------------------------------------------------------------
echo [2/4] Checking JDK ...
java -version >nul 2>&1
if errorlevel 1 (
    echo.
    echo   ERROR: java not found. Install JDK 17+ and add it to PATH.
    echo.
    if not defined NOPAUSE pause
    exit /b 1
)
echo     JDK found

REM ---------------------------------------------------------------
REM [3/4] Build the APK
REM ---------------------------------------------------------------
echo [3/4] Building APK ...
pushd android
call .\gradlew.bat --console=plain assembleDebug
set GRADLE_EXIT=%errorlevel%
popd
if not "%GRADLE_EXIT%"=="0" (
    echo.
    echo   ERROR: Android build failed, see the log above.
    if not defined NOPAUSE pause
    exit /b 1
)

REM ---------------------------------------------------------------
REM [4/4] Copy the APK into dist\
REM ---------------------------------------------------------------
echo [4/4] Copying APK to dist ...
set APK=android\app\build\outputs\apk\debug\app-debug.apk
if not exist "%APK%" (
    echo   ERROR: %APK% was not produced.
    if not defined NOPAUSE pause
    exit /b 1
)
mkdir "dist\android" 2>nul
copy /y "%APK%" "dist\android\ncmp-mobile.apk" >nul

echo.
echo ============================================
echo   BUILD OK
echo ============================================
echo   APK: dist\android\ncmp-mobile.apk
echo.
if not defined NOPAUSE pause
endlocal
