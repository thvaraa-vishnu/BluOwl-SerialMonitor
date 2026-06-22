@echo off
cd /d "%~dp0"
setlocal enabledelayedexpansion
:: ─────────────────────────────────────────────────────────────────────────────
:: nuitka_build_exe_v2_1.bat  —  Nuitka EXE Builder for BluOwl SerialMonitor
:: Version history:
::   v1.0  Initial Nuitka build script (replaced PyInstaller)
::   v1.1  Added icon extraction from embedded base64 in .py file
::   v1.2  Added pause on every error exit + [STEP x/8] progress markers
::   v1.3  Added --onefile-tempdir-spec for persistent cache (fast re-launch)
::   v1.4  EXE copied to main folder after build; opens main folder in Explorer
::   v1.5  Naming convention changed to BluOwl_SerialMonitor_V_x.xx for EXE
::   v1.6  Renamed temp build icon file to bluowl_temp_icon.ico
::   v1.7  Added old Nuitka cache cleanup before build
::   v1.8  Tempdir spec includes version to prevent version collisions
::   v1.9  Full nuclear clean — all Nuitka caches, dist, build folders wiped
::   v2.0  Added --disable-cache=all to force 100%% fresh recompile every time
::         Added __pycache__, LOCALAPPDATA\Nuitka and TEMP\Nuitka to clean list
::         File renamed to match version: nuitka_build_exe_v2_0.bat
::   v2.1  Added cd /d "%~dp0" so bat always runs from its own folder regardless
::         of where it is launched from (fixes "No .py file found" when invoked
::         from a different working directory)
::         File renamed to match version: nuitka_build_exe_v2_1.bat
:: ─────────────────────────────────────────────────────────────────────────────
title BluOwl SerialMonitor — Nuitka EXE Builder  v2.1
color 0B
echo.
echo  =============================================
echo   BluOwl SerialMonitor  —  Nuitka EXE Builder  v2.1
echo  =============================================
echo.

:: ── Check Python ──────────────────────────────────────────────────────────────
echo  [STEP 1/9] Checking Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo  [ERROR] Python not found.
    echo  Download from https://www.python.org/downloads/
    echo  Tick "Add Python to PATH" during install.
    echo.
    pause & exit /b 1
)
for /f "tokens=*" %%i in ('python --version') do echo  [OK] %%i found.

:: ── Check Nuitka ──────────────────────────────────────────────────────────────
echo.
echo  [STEP 2/9] Checking Nuitka...
python -m nuitka --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo  [ERROR] Nuitka not found.
    echo  Run:  pip install nuitka
    echo  Also ensure Visual Studio Build Tools is installed with
    echo  "Desktop development with C++" workload.
    echo.
    pause & exit /b 1
)
for /f "tokens=*" %%i in ('python -m nuitka --version') do echo  [OK] Nuitka %%i found.

:: ── Auto-detect the .py file ───────────────────────────────────────────────────
echo.
echo  [STEP 3/9] Searching for .py file...
set PY_FILE=
for %%f in (*.py) do (
    if not "%%f"=="extract_icon.py" set PY_FILE=%%f
)
if "!PY_FILE!"=="" (
    echo.
    echo  [ERROR] No .py file found in this folder.
    echo.
    pause & exit /b 1
)
echo  [OK] Found: !PY_FILE!

:: ── Extract version ────────────────────────────────────────────────────────────
set APP_VERSION=
for /f "tokens=3 delims= " %%v in ('findstr /i "APP_VERSION" "!PY_FILE!"') do (
    if "!APP_VERSION!"=="" set APP_VERSION=%%v
)
set APP_VERSION=!APP_VERSION:"=!
if "!APP_VERSION!"=="" (
    set APP_VERSION=1.0
    echo  [WARN] Could not read APP_VERSION, defaulting to 1.0
) else (
    echo  [OK] Version: v!APP_VERSION!
)
for %%f in (!PY_FILE!) do set EXE_NAME=%%~nf
set FINAL_NAME=BluOwl_SerialMonitor_V_!APP_VERSION!
echo  [OK] EXE name: !FINAL_NAME!.exe

:: ── Install / upgrade dependencies ────────────────────────────────────────────
echo.
echo  [STEP 4/9] Installing dependencies...
python -m pip install --upgrade pyserial PyQt6 numpy nuitka --quiet
if errorlevel 1 (
    echo.
    echo  [ERROR] pip install failed. Check your internet connection.
    echo.
    pause & exit /b 1
)
echo  [OK] All dependencies ready.

:: ── NUCLEAR CLEAN — wipe everything from previous builds ─────────────────────
echo.
echo  [STEP 5/9] Full clean of all previous build artefacts...

:: Local build/dist folders
if exist "dist"                   rmdir /s /q "dist"
if exist "!FINAL_NAME!.build"     rmdir /s /q "!FINAL_NAME!.build"
if exist "!FINAL_NAME!.dist"      rmdir /s /q "!FINAL_NAME!.dist"

:: Any leftover .build or .dist folders from any version
for /d %%d in ("*.build") do rmdir /s /q "%%d" >nul 2>&1
for /d %%d in ("*.dist")  do rmdir /s /q "%%d" >nul 2>&1

:: Python bytecode cache in project folder
if exist "__pycache__"            rmdir /s /q "__pycache__" >nul 2>&1
for %%f in ("*.pyc")              do del /q "%%f" >nul 2>&1

:: Nuitka C compilation cache — APPDATA\Nuitka
if exist "%APPDATA%\Nuitka"       rmdir /s /q "%APPDATA%\Nuitka" >nul 2>&1

:: Nuitka C compilation cache — LOCALAPPDATA\Nuitka (newer Nuitka versions)
if exist "%LOCALAPPDATA%\Nuitka"  rmdir /s /q "%LOCALAPPDATA%\Nuitka" >nul 2>&1

:: Nuitka C compilation cache — TEMP\Nuitka
if exist "%TEMP%\Nuitka"          rmdir /s /q "%TEMP%\Nuitka" >nul 2>&1

:: ALL previous app onefile caches in LOCALAPPDATA (every name variant)
for %%n in ("UART Logger" "UART_Logger" "BluOwl SerialMonitor" "BluOwl_SerialMonitor" "BluOwl") do (
    if exist "%LOCALAPPDATA%\%%~n" (
        rmdir /s /q "%LOCALAPPDATA%\%%~n" >nul 2>&1
        echo  [OK] Removed cache: %%~n
    )
)

:: Previous EXE in main folder
for %%f in ("BluOwl_SerialMonitor_V_*.exe") do del /q "%%f" >nul 2>&1

echo  [OK] Full clean done — building 100%% from scratch.

:: ── Extract embedded icon ─────────────────────────────────────────────────────
echo.
echo  [STEP 6/9] Extracting embedded icon...
(
echo import re, base64, sys
echo src = open(sys.argv[1], encoding='utf-8'^).read(^)
echo m = re.search(r'_ICON_B64\s*=\s*"([A-Za-z0-9+/=]+)"', src^)
echo if m:
echo     open('bluowl_temp_icon.ico', 'wb'^).write(base64.b64decode(m.group(1^)^)^)
echo     print('[OK] Icon extracted.'^)
echo else:
echo     print('[WARN] Icon not found in script.'^)
echo     sys.exit(1^)
) > extract_icon.py

python extract_icon.py "!PY_FILE!"
if errorlevel 1 (
    echo  [WARN] Building without custom icon.
    set ICON_FLAG=
) else (
    if exist bluowl_temp_icon.ico (
        set ICON_FLAG=--windows-icon-from-ico=bluowl_temp_icon.ico
        echo  [OK] Icon ready.
    ) else (
        set ICON_FLAG=
    )
)

:: ── Build EXE ─────────────────────────────────────────────────────────────────
echo.
echo  [STEP 7/9] Building !FINAL_NAME!.exe ...
echo  This takes 3-5 minutes on first build.
echo.

python -m nuitka ^
    --onefile ^
    --disable-cache=all ^
    --onefile-tempdir-spec="{CACHE_DIR}/{COMPANY}/{PRODUCT}/{VERSION}" ^
    --windows-console-mode=disable ^
    --windows-file-version=!APP_VERSION! ^
    --windows-product-version=!APP_VERSION! ^
    --windows-file-description="BluOwl SerialMonitor - Serial Terminal" ^
    --windows-product-name="BluOwl SerialMonitor" ^
    --windows-company-name="BluOwl SerialMonitor" ^
    !ICON_FLAG! ^
    --output-filename="!FINAL_NAME!.exe" ^
    --output-dir=dist ^
    --enable-plugin=pyqt6 ^
    --include-package=serial ^
    --include-package=numpy ^
    --assume-yes-for-downloads ^
    "!PY_FILE!"

if errorlevel 1 (
    echo.
    echo  =============================================
    echo  [ERROR] Build failed. See output above.
    echo  Common causes:
    echo    - Visual Studio Build Tools not installed
    echo    - Missing "Desktop development with C++" workload
    echo    - Run:  pip install nuitka --upgrade
    echo  =============================================
    echo.
    del /q bluowl_temp_icon.ico >nul 2>&1
    del /q extract_icon.py >nul 2>&1
    pause & exit /b 1
)

:: ── Tidy up ───────────────────────────────────────────────────────────────────
echo.
echo  [STEP 8/9] Cleaning up temp build files...
rmdir /s /q "!FINAL_NAME!.build" >nul 2>&1
del /q bluowl_temp_icon.ico >nul 2>&1
del /q extract_icon.py >nul 2>&1
echo  [OK] Done.

:: ── Copy EXE to main folder ───────────────────────────────────────────────────
echo.
echo  [STEP 9/9] Copying EXE to main folder...
copy /y "dist\!FINAL_NAME!.exe" "!FINAL_NAME!.exe" >nul
if errorlevel 1 (
    echo  [WARN] Copy failed. Find EXE in dist\ folder.
) else (
    echo  [OK] EXE ready: %CD%\!FINAL_NAME!.exe
)

:: ── Report ────────────────────────────────────────────────────────────────────
echo.
echo  =============================================
echo   BUILD SUCCESSFUL!
echo.
echo   !FINAL_NAME!.exe  (main folder)
echo   dist\!FINAL_NAME!.exe  (dist folder)
echo.
echo   Built clean from: !PY_FILE!
echo   All previous caches wiped — first launch
echo   will extract fresh, then fast every time.
echo  =============================================
echo.

for %%f in ("dist\!FINAL_NAME!.exe") do (
    set /a sz=%%~zf / 1048576
    echo   EXE size: !sz! MB
)
echo.
explorer .
pause
