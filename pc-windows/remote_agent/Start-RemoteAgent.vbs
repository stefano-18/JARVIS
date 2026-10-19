' Start-RemoteAgent.vbs - lanza remote_agent (Jarvis2) oculto, idempotente.
' Mismo patron que StartJarvisV2Fijo.vbs: solo lanza si no corre ya.
' Guarda principal: agent.lock con PID (gestionado por agent.py).
' Respaldo: este chequeo WMI evita spawnear un segundo proceso.
' Arranque: Tarea Programada JarvisRemoteAgent (logon +15s) + copia en Startup.
Option Explicit
CreateObject("WScript.Shell").Run "powershell -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File C:\jarvis_agent\remote_agent\actualizar-apps.ps1", 0, True
Dim wmi, procs, p, agentRun
agentRun = False
Set wmi = GetObject("winmgmts:\\.\root\cimv2")
Set procs = wmi.ExecQuery("SELECT CommandLine FROM Win32_Process WHERE Name='python.exe' OR Name='pythonw.exe'")
For Each p In procs
  If Not IsNull(p.CommandLine) Then
    If InStr(p.CommandLine, "remote_agent\agent.py") > 0 Then agentRun = True
  End If
Next
If Not agentRun Then
  Dim sh
  Set sh = CreateObject("WScript.Shell")
  sh.Run """{{WIN_HOME}}\AppData\Local\Programs\Python\Python311\pythonw.exe"" ""C:\jarvis_agent\remote_agent\agent.py""", 0, False
End If
