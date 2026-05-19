' start_hidden.vbs — Runs the attendance engine in headless mode with no visible window.
' Place this file (or a shortcut to it) in the Windows Startup folder:
'   Win+R -> shell:startup -> paste shortcut
'
' The engine runs silently in the background. Logs go to office_engine.log.

Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

' Resolve project directory (two levels up from this script)
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
projectDir = fso.GetParentFolderName(scriptDir)

' Run headless engine with PYTHONPATH set, completely hidden (window style 0)
WshShell.CurrentDirectory = projectDir
WshShell.Run "cmd /c set PYTHONPATH=" & projectDir & " && py -3.12 -m office_engine.run", 0, False
