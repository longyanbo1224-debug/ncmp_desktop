@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo   ncmp desktop Build
echo ============================================
echo.

echo [0/4] Closing running ncmp desktop.exe ...
taskkill /f /im "ncmp desktop.exe" >nul 2>&1

echo [1/4] Checking dependencies ...
pip install pyinstaller qtawesome pyncm PySide6 keyring qrcode Pillow pycryptodome PyNaCl requests >nul 2>&1

echo [2/4] Cleaning old build artifacts ...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist "ncmp desktop.spec" del /q "ncmp desktop.spec"

echo [3/4] Building (1-2 minutes, please wait) ...
pyinstaller --noconsole --windowed -y --name "ncmp desktop" --icon resources\app.ico --collect-all qtawesome --collect-all pyncm --add-data "app\ui\styles\light.qss;ui\styles" --add-data "resources\workflow_example.yml;resources" --hidden-import keyring.backends --hidden-import keyring.backends.Windows --exclude-module PySide6.QtWebEngineWidgets --exclude-module PySide6.QtWebEngineCore --exclude-module PySide6.QtWebEngineQuick --exclude-module PySide6.QtQml --exclude-module PySide6.QtQuick --exclude-module PySide6.QtQuick3D --exclude-module PySide6.QtQuickWidgets --exclude-module PySide6.Qt3DCore --exclude-module PySide6.Qt3DRender --exclude-module PySide6.QtCharts --exclude-module PySide6.QtDataVisualization --exclude-module PySide6.QtMultimedia --exclude-module PySide6.QtMultimediaWidgets --exclude-module PySide6.QtPdf --exclude-module PySide6.QtPdfWidgets --exclude-module PySide6.QtSql --exclude-module PySide6.QtTest --exclude-module torch --exclude-module tensorflow --exclude-module pandas --exclude-module scipy --exclude-module matplotlib --exclude-module IPython --exclude-module jupyter --exclude-module notebook app\main.py

if errorlevel 1 (
    echo.
    echo === BUILD FAILED, see log above ===
    if not defined NOPAUSE pause
    exit /b 1
)

echo [4/4] Done.
echo.
echo ============================================
echo   Build OK
echo ============================================
echo Executable:  %~dp0dist\ncmp desktop\ncmp desktop.exe
echo Tip: Right-click ncmp desktop.exe -^> Send to -^> Desktop (create shortcut)
echo.
explorer /select,"%~dp0dist\ncmp desktop\ncmp desktop.exe"
if not defined NOPAUSE pause
