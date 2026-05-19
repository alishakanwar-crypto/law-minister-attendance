@echo off
REM start_attendance.bat — Runs the attendance engine in headless mode.
REM Place this file (or start_hidden.vbs) in the Windows Startup folder:
REM   Win+R -> shell:startup -> paste file
REM
REM To run with GUI instead, change "office_engine.run" to "office_engine.gui_app"

cd /d "%~dp0.."
set PYTHONPATH=%CD%
py -3.12 -m office_engine.run
