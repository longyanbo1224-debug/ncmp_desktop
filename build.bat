@echo off
REM ===================================================================
REM  ncmp desktop - one-click build script
REM
REM  NOTE: keep every message in this file ASCII-only.
REM  cmd.exe parses .bat files byte-by-byte using the code page that was
REM  active when it started reading, so non-ASCII text (e.g. Chinese)
REM  desynchronises the parser and lines get executed as commands.
REM  "chcp 65001" only changes console OUTPUT, not how the file is read.
REM  This is why the whole script is in English.
REM
REM  Also: this file must use CRLF line endings. LF-only breaks the
REM  multi-line IF blocks and the "^" line continuations below.
REM ===================================================================
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo ============================================
echo   ncmp desktop - build
echo ============================================
echo.

REM ---------------------------------------------------------------
REM [0/8] Close a running instance (the exe is locked while running)
REM ---------------------------------------------------------------
echo [0/8] Closing running ncmp desktop.exe ...
taskkill /f /im "ncmp desktop.exe" >nul 2>&1

REM ---------------------------------------------------------------
REM [1/8] Check Python
REM ---------------------------------------------------------------
echo [1/8] Checking Python ...
python --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo   ERROR: "python" not found.
    echo   Install Python 3.10+ and tick "Add Python to PATH":
    echo   https://www.python.org/downloads/
    echo.
    if not defined NOPAUSE pause
    exit /b 1
)
for /f "delims=" %%v in ('python --version 2^>^&1') do echo     %%v

REM ---------------------------------------------------------------
REM [2/8] Check required resources.
REM       The fonts are binaries; if a clone drops them the build
REM       still "succeeds" but the app ships without CJK fonts.
REM ---------------------------------------------------------------
echo [2/8] Checking resource files ...
set MISSING=
if not exist "app\ui\fonts\NCMPSansSC-Regular.ttf"  set MISSING=%MISSING% app\ui\fonts\NCMPSansSC-Regular.ttf
if not exist "app\ui\fonts\NCMPSansSC-SemiBold.ttf" set MISSING=%MISSING% app\ui\fonts\NCMPSansSC-SemiBold.ttf
if not exist "app\ui\fonts\NCMPSerifSC-Bold.ttf"     set MISSING=%MISSING% app\ui\fonts\NCMPSerifSC-Bold.ttf
if not exist "app\ui\styles\check.png"              set MISSING=%MISSING% app\ui\styles\check.png
if not exist "resources\app.ico"                    set MISSING=%MISSING% resources\app.ico
if not exist "resources\workflow_example.yml"       set MISSING=%MISSING% resources\workflow_example.yml
if defined MISSING (
    echo.
    echo   ERROR: missing resource files:
    for %%f in (%MISSING%) do echo     %%f
    echo.
    echo   Regenerate fonts with: python scripts\make_fonts.py
    echo   It needs Noto Sans SC / Noto Serif SC installed on this machine.
    echo.
    if not defined NOPAUSE pause
    exit /b 1
)
echo     all present

REM ---------------------------------------------------------------
REM [3/8] Install dependencies.
REM       Must go through requirements.txt: pyncm is NOT on PyPI,
REM       a plain "pip install pyncm" grabs the wrong package.
REM ---------------------------------------------------------------
echo [3/8] Installing dependencies - slow on first run ...
python -m pip install --upgrade pyinstaller
if errorlevel 1 (
    echo.
    echo   ERROR: failed to install pyinstaller. Check network / pip index.
    if not defined NOPAUSE pause
    exit /b 1
)
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo   ERROR: failed to install dependencies.
    echo   pyncm in requirements.txt is installed from github.com.
    echo   If github is unreachable, use the tarball method noted
    echo   in the comments of requirements.txt.
    echo.
    if not defined NOPAUSE pause
    exit /b 1
)

REM ---------------------------------------------------------------
REM [4/8] Clean previous output
REM ---------------------------------------------------------------
echo [4/8] Cleaning previous output ...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist "ncmp desktop.spec" del /q "ncmp desktop.spec"

REM ---------------------------------------------------------------
REM [5/8] Build.
REM       Deliberately NOT using --collect-all PySide6: that pulls in
REM       every Qt plugin / QML / translation and blows the size up to
REM       the GB range. PyInstaller's own PySide6 hook only collects
REM       what is actually imported.
REM ---------------------------------------------------------------
echo [5/8] Building - about 1-2 minutes ...
pyinstaller --noconsole --windowed --clean -y ^
  --name "ncmp desktop" ^
  --icon resources\app.ico ^
  --collect-all qtawesome ^
  --collect-all pyncm ^
  --add-data "app\ui\fonts;ui\fonts" ^
  --add-data "app\ui\styles\check.png;ui\styles" ^
  --add-data "resources\workflow_example.yml;resources" ^
  --hidden-import keyring.backends ^
  --hidden-import keyring.backends.Windows ^
  --exclude-module PySide6.QtWebEngineWidgets ^
  --exclude-module PySide6.QtWebEngineCore ^
  --exclude-module PySide6.QtWebEngineQuick ^
  --exclude-module PySide6.QtQml ^
  --exclude-module PySide6.QtQuick ^
  --exclude-module PySide6.QtQuick3D ^
  --exclude-module PySide6.QtQuickWidgets ^
  --exclude-module PySide6.Qt3DCore ^
  --exclude-module PySide6.Qt3DRender ^
  --exclude-module PySide6.QtCharts ^
  --exclude-module PySide6.QtDataVisualization ^
  --exclude-module PySide6.QtMultimedia ^
  --exclude-module PySide6.QtMultimediaWidgets ^
  --exclude-module PySide6.QtPdf ^
  --exclude-module PySide6.QtPdfWidgets ^
  --exclude-module PySide6.QtSql ^
  --exclude-module PySide6.QtTest ^
  --exclude-module torch ^
  --exclude-module tensorflow ^
  --exclude-module pandas ^
  --exclude-module scipy ^
  --exclude-module matplotlib ^
  --exclude-module IPython ^
  --exclude-module jupyter ^
  --exclude-module notebook ^
  app\main.py

if errorlevel 1 (
    echo.
    echo   ERROR: build failed, see the log above.
    if not defined NOPAUSE pause
    exit /b 1
)

REM ---------------------------------------------------------------
REM [6/8] Verify the output.
REM       A "successful" build is not a working build: if a resource
REM       was not bundled you only find out at runtime.
REM ---------------------------------------------------------------
echo [6/8] Verifying output ...
set EXE=dist\ncmp desktop\ncmp desktop.exe
if not exist "%EXE%" (
    echo   ERROR: %EXE% was not produced.
    if not defined NOPAUSE pause
    exit /b 1
)

set PROBLEM=
if not exist "dist\ncmp desktop\_internal\ui\fonts\NCMPSansSC-Regular.ttf" set PROBLEM=%PROBLEM% fonts
if not exist "dist\ncmp desktop\_internal\ui\styles\check.png"              set PROBLEM=%PROBLEM% checkbox-icon
if not exist "dist\ncmp desktop\_internal\resources\workflow_example.yml"   set PROBLEM=%PROBLEM% workflow-template
if defined PROBLEM (
    echo.
    echo   ERROR: these resources were NOT bundled:%PROBLEM%
    echo   The app will start but the related features will misbehave.
    echo.
    if not defined NOPAUSE pause
    exit /b 1
)
echo     resources bundled correctly

REM ---------------------------------------------------------------
echo   Android APK:  dist\android\ncmp-mobile.apk   ^(if Android SDK was set up^)
REM ---------------------------------------------------------------
echo   Android APK:  dist\android\ncmp-mobile.apk   ^(if Android SDK was set up^)
set APK=android\app\build\outputs\apk\debug\app-debug.apk
set HAVE_SDK=0
if exist "android\local.properties" set HAVE_SDK=1
if defined ANDROID_HOME set HAVE_SDK=1
if not "%HAVE_SDK%"=="1" (
    echo     Android SDK not found - skipping APK build.
    echo     Set ANDROID_HOME or create android\local.properties, then re-run.
    goto android_done
)
pushd android
call gradlew.bat --no-daemon --console=plain assembleDebug
set GRADLE_EXIT=%errorlevel%
popd
if not "%GRADLE_EXIT%"=="0" (
    echo.
    echo   ERROR: Android build failed, see the log above.
    if not defined NOPAUSE pause
    exit /b 1
)
if not exist "%APK%" (
    echo   ERROR: %APK% was not produced.
    if not defined NOPAUSE pause
    exit /b 1
)
echo     APK built
:android_done

REM ---------------------------------------------------------------
REM [8/8] Copy the APK into dist\
REM ---------------------------------------------------------------
echo [8/8] Copying APK to dist ...
if exist "%APK%" (
    mkdir "dist\android" 2>nul
    copy /y "%APK%" "dist\android\ncmp-mobile.apk" >nul
    echo     dist\android\ncmp-mobile.apk
)


echo.
echo ============================================
echo   BUILD OK
echo ============================================
echo   Executable: %~dp0%EXE%
echo   Android APK:  dist\android\ncmp-mobile.apk   ^(if Android SDK was set up^)
cmp-mobile.apk   ^(if Android SDK was set up^)
echo.
echo   When distributing, zip the WHOLE "dist\ncmp desktop" folder.
echo   Do NOT ship the exe alone - it needs the _internal\ folder
echo   sitting next to it.
echo.
explorer /select,"%~dp0%EXE%"
if not defined NOPAUSE pause
endlocal
