' friday-app.vbs — FRIDAY V3 (M48)
' Launch FRIDAY as a proper windowless app: no console, no terminal spam.
' Uses the provisioned venv's pythonw.exe (GUI Python, no console) and runs
' the bootstrap → launcher, which brings up the system-tray presence. Logs go
' to data\logs\friday.log (the tray's "Open logs" opens that folder).
'
' Placed at the install root; the Desktop / Start-Menu shortcut and the
' `friday` command's --app mode point here.

Option Explicit
Dim fso, shell, here, pyw, boot
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

here = fso.GetParentFolderName(WScript.ScriptFullName)
' walk up from deploy\windows\ to the install root
here = fso.GetParentFolderName(fso.GetParentFolderName(here))

pyw = here & "\.venv\Scripts\pythonw.exe"
boot = here & "\deploy\bootstrap.py"

If fso.FileExists(pyw) And fso.FileExists(boot) Then
    shell.CurrentDirectory = here
    ' 0 = hidden window, False = don't wait — fully detached, no console
    shell.Run """" & pyw & """ """ & boot & """", 0, False
Else
    MsgBox "FRIDAY is not fully installed yet (missing venv or bootstrap)." & _
           vbCrLf & "Run the installer again, then retry.", 48, "FRIDAY"
End If
