Option Explicit
Dim fso, shell, base, pythonw, entry
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
base = fso.GetParentFolderName(WScript.ScriptFullName)
pythonw = base & "\.venv\Scripts\pythonw.exe"
entry = base & "\main.py"
If Not fso.FileExists(pythonw) Then
  MsgBox "Run SETUP_WINDOWS.bat first.", 48, "Local AI Agent"
  WScript.Quit 1
End If
shell.CurrentDirectory = base
shell.Run Chr(34) & pythonw & Chr(34) & " " & Chr(34) & entry & Chr(34), 1, False
