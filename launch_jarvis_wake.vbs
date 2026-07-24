Option Explicit

Dim shell, fso, baseDir, pythonw, launcher, command, localAppData
Dim versions, version, candidate
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

baseDir = fso.GetParentFolderName(WScript.ScriptFullName)
launcher = baseDir & "\jarvis_launcher.py"
localAppData = shell.ExpandEnvironmentStrings("%LOCALAPPDATA%")
pythonw = ""

' Startup-folder programs can run before Windows finishes initialising audio.
WScript.Sleep 8000

' Prefer the newest supported per-user Python without binding startup to one
' exact minor version.
versions = Array("314", "313", "312", "311", "310", "39")
For Each version In versions
    candidate = localAppData & "\Programs\Python\Python" & version & "\pythonw.exe"
    If fso.FileExists(candidate) Then
        pythonw = candidate
        Exit For
    End If
Next

If pythonw = "" Then
    MsgBox "No se encontro una instalacion compatible de Python.", _
        16, "J.A.R.V.I.S Mark LI"
    WScript.Quit 1
End If

command = Chr(34) & pythonw & Chr(34) & " " & _
    Chr(34) & launcher & Chr(34) & " --mode wake"
shell.Run command, 0, False
