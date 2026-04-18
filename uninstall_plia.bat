@echo off
REM =============================================================
REM   Plia Uninstaller - self-elevating launcher
REM   Placement: anywhere (Desktop, C:\Plia, USB stick, ...)
REM   Run:       double-click, or right-click > Run as admin.
REM =============================================================

setlocal enableextensions enabledelayedexpansion

REM ---- Re-entry marker (set when running from %TEMP%\plia_uninstall) -----
if /I "%~1"=="__staged__" goto staged

REM ---------------------- Self-elevate -------------------------
net session >nul 2>&1
if errorlevel 1 (
    echo Requesting administrator privileges...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

REM ---------------------- Validate source ----------------------
set "SRC=%~dp0"
if not exist "%SRC%uninstall_plia.py" (
    echo.
    echo  [ERROR] uninstall_plia.py must be in the same folder as uninstall_plia.bat
    echo          Looked for: %SRC%uninstall_plia.py
    echo.
    pause
    exit /b 1
)

REM ---- Stage both files to %TEMP% so C:\Plia\ can be safely deleted ----
set "STAGE=%TEMP%\plia_uninstall"
if exist "%STAGE%" rmdir /S /Q "%STAGE%" >nul 2>&1
mkdir "%STAGE%" >nul 2>&1
copy /Y "%~f0"                  "%STAGE%\uninstall_plia.bat" >nul
copy /Y "%SRC%uninstall_plia.py" "%STAGE%\uninstall_plia.py" >nul

REM ---- Launch the staged copy detached and exit this instance ---
start "Plia Uninstaller" cmd /c ""%STAGE%\uninstall_plia.bat" __staged__"
exit /b


:staged
REM ============= Running from %TEMP%\plia_uninstall =============
cd /d "%~dp0"

REM ---------------------- Locate Python ------------------------
set "PYEXE="
where python >nul 2>&1 && set "PYEXE=python"
if not defined PYEXE (
    where py >nul 2>&1 && set "PYEXE=py -3"
)
if not defined PYEXE (
    echo.
    echo  [ERROR] Python 3.11+ is required but was not found on your PATH.
    echo          Install Python from https://www.python.org/downloads/
    echo          ^(make sure "Add Python to PATH" is ticked^), or open
    echo          an Anaconda Prompt, and try again.
    echo.
    pause
    exit /b 1
)

REM ---------------------- Sanity-check tkinter -----------------
%PYEXE% -c "import tkinter" >nul 2>&1
if errorlevel 1 (
    echo.
    echo  [ERROR] The detected Python does not include tkinter.
    echo          Reinstall Python with the "tcl/tk and IDLE" option enabled.
    echo.
    pause
    exit /b 1
)

echo.
echo  Launching Plia Uninstaller GUI...
echo.
%PYEXE% "%~dp0uninstall_plia.py"

REM staging in %TEMP% is self-cleaning - Windows purges %TEMP% on schedule
exit /b
