@echo off
REM ============================================================
REM  Law Minister Office Attendance Engine — Windows Auto-Start
REM  This script creates a Windows Task Scheduler entry to run
REM  the attendance engine automatically on system startup.
REM
REM  Works with both:
REM    - Standalone .exe build (LawMinisterOfficeEngine.exe)
REM    - Python source (python -m office_engine.run)
REM ============================================================

echo.
echo  LAW MINISTER OFFICE — ATTENDANCE ENGINE INSTALLER
echo  ==================================================
echo.

REM Check for admin rights
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo  ERROR: Please run this script as Administrator.
    echo  Right-click and select "Run as administrator"
    pause
    exit /b 1
)

REM Get the current directory
set SCRIPT_DIR=%~dp0
set ENGINE_DIR=%SCRIPT_DIR%

REM Check if .exe build exists
if exist "%ENGINE_DIR%LawMinisterOfficeEngine.exe" (
    echo  Found standalone .exe build.
    set EXE_PATH=%ENGINE_DIR%LawMinisterOfficeEngine.exe

    REM Create Task Scheduler entry for .exe
    schtasks /create /tn "LawMinisterAttendance" /tr "\"%EXE_PATH%\"" /sc onlogon /rl highest /f

    if %errorLevel% equ 0 (
        echo.
        echo  SUCCESS: Attendance engine will start automatically on login.
        echo.
        echo  Executable: %EXE_PATH%
        echo  Task name: LawMinisterAttendance
        echo  To remove: schtasks /delete /tn "LawMinisterAttendance" /f
    ) else (
        echo  ERROR: Failed to create scheduled task.
    )
) else (
    echo  No .exe found. Using Python source mode.

    REM Check Python is available
    python --version >nul 2>&1
    if %errorLevel% neq 0 (
        echo  ERROR: Python not found. Please install Python 3.10+ first.
        pause
        exit /b 1
    )

    REM Create the startup script
    echo @echo off > "%ENGINE_DIR%start_engine.bat"
    echo cd /d "%ENGINE_DIR%.." >> "%ENGINE_DIR%start_engine.bat"
    echo python -m office_engine.run >> "%ENGINE_DIR%start_engine.bat"

    REM Create Task Scheduler entry
    schtasks /create /tn "LawMinisterAttendance" /tr "\"%ENGINE_DIR%start_engine.bat\"" /sc onlogon /rl highest /f

    if %errorLevel% equ 0 (
        echo.
        echo  SUCCESS: Attendance engine will start automatically on login.
        echo.
        echo  To start now:    python -m office_engine.run
        echo  To check status: python -m office_engine.run --status
        echo  To sync once:    python -m office_engine.run --sync
        echo.
        echo  Task name: LawMinisterAttendance
        echo  To remove: schtasks /delete /tn "LawMinisterAttendance" /f
    ) else (
        echo  ERROR: Failed to create scheduled task.
    )
)

pause
