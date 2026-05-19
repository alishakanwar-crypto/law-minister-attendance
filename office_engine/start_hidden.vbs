' start_hidden.vbs — Runs the attendance engine in headless mode with no visible window.
' Place this file (or a shortcut to it) in the Windows Startup folder:
'   Win+R -> shell:startup -> paste shortcut
'
' The engine runs silently in the background. Logs go to office_engine.log.
' On each boot it pulls the latest code from git before starting.

Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

' Resolve project directory (two levels up from this script)
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
projectDir = fso.GetParentFolderName(scriptDir)

' Pull latest code, then run headless engine — completely hidden (window style 0)
WshShell.CurrentDirectory = projectDir
WshShell.Run "cmd /c cd /d """ & projectDir & """ && git pull origin devin/1778828096-face-registration 2>>office_engine.log && set PYTHONPATH=" & projectDir & " && py -3.12 -m office_engine.run", 0, False
