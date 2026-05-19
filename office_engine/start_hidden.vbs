' start_hidden.vbs — Watchdog that keeps the attendance engine running forever.
' Place this file (or a shortcut to it) in the Windows Startup folder:
'   Win+R -> shell:startup -> paste shortcut
'
' The engine runs silently in the background. Logs go to office_engine.log.
' If the engine crashes or is closed, the watchdog restarts it after 30 seconds.
' On each restart it pulls the latest code from git.

Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

' Resolve project directory (two levels up from this script)
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
projectDir = fso.GetParentFolderName(scriptDir)

WshShell.CurrentDirectory = projectDir

' Watchdog loop — restart engine forever
Do While True
    ' Pull latest code, then run engine (WshShell.Run with True waits for it to finish)
    WshShell.Run "cmd /c cd /d """ & projectDir & """ && git pull origin devin/1778828096-face-registration >>office_engine.log 2>&1 && set PYTHONPATH=" & projectDir & " && py -3.12 -m office_engine.run >>office_engine.log 2>&1", 0, True

    ' Engine exited — wait 30 seconds before restarting
    WScript.Sleep 30000
Loop
