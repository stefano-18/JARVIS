' JARVIS (arreglo 74): ejecuta exportar_nombres.ps1 sin abrir ninguna ventana
CreateObject("WScript.Shell").Run "powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File ""{{WIN_HOME}}\JARVIS-pron\exportar_nombres.ps1""", 0, False
