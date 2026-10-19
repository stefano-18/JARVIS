---
name: control-pc
description: Control del PC fijo por Telegram (abrir/cerrar apps, captura, multimedia, portapapeles, archivos, WOL, herramientas). LOW sin palabra, HIGH con modo seguro.
metadata:
  {
    "openclaw":
      {
        "requires": { "bins": ["python3"], "os": ["linux"] },
      },
  }
---

# Control del PC fijo (Telegram)

Runner: `python3 {{HOME}}/jarvis2/scripts/pc_do.py <cmd>` o `python3 {{HOME}}/jarvis2/scripts/wake_pc.py`.
Nunca muestres secretos (MAC, IPs completas, tokens).

## Acciones LOW (sin palabra clave)

Ejecuta SIEMPRE con la herramienta `exec` en silencio. NUNCA escribas el
comando en el chat (nada que empiece por `!`, nada de rutas ni scripts
visibles). Runner: `python3 {{HOME}}/jarvis2/scripts/pc_do.py <cmd>`
o `python3 {{HOME}}/jarvis2/scripts/wake_pc.py`.

| Lo que pide el usuario | Subcomando de `pc_do.py` |
|---|---|
| "abre X en el PC" | `open X` |
| "cierra X en el PC" | `close X` |
| "captura el PC" / "screenshot" | `screenshot` |
| "volumen X%" / "mute" / "unmute" | `volume <level>` |
| "portapapeles" / "clipboard" | `clipboard` |
| "lista archivos <ruta>" | `files <ruta>` |
| "descarga <url>" | `download <url>` |
| "estado del PC" | `status` |
| "enciende el PC" / "despierta el PC" | `wake_pc.py` (el otro script) |
| "abre el ojo de dios" | `open {{WIN_HOME}}\herramientas\gods-eye-view\abrir-gods-eye.bat` |

Resume la salida en UNA frase natural. Sin comandos, sin JSON, sin rutas.

## Acciones HIGH (requieren modo seguro)

Antes de ejecutar CUALQUIER acción HIGH, comprueba el modo seguro con la
herramienta `exec` (nunca en el chat):

`python3 {{HOME}}/jarvis-control/jarvis_gate.py check-high`

Si la salida es `DENIED`, responde al usuario: `Esto necesita tu palabra clave`.
Si la salida es `OK`, ejecuta la acción (también vía `exec`) y resume el
resultado en una frase natural:

| Lo que pide el usuario | Subcomando de `pc_do.py` |
|---|---|
| "borra <archivo>" | `delete <ruta>` |
| "winget X" | `winget <pkg>` |
| "powershell <cmd>" | `shell <cmd>` |
| "apaga el PC" | `shutdown --yes` |
| "reinicia el PC" | `restart --yes` |
| "suspende el PC" | `suspend --yes` |
| "actualiza juego <nombre>" | `game update <nombre>` |
| "lanza juego <nombre>" | `open <nombre>` |

## Reglas

- Informa el RESULTADO en una frase corta, en lenguaje natural.
- NUNCA escribas comandos en el chat (nada con `!`), ni rutas
  (`/home/...`, `C:\...`), ni nombres de scripts, ni JSON, ni codigo.
  Todo se ejecuta con `exec` en silencio y solo se cuenta el resultado.
- Nunca muestres la MAC completa, IPs, ni rutas absolutas completas si no es necesario.
- Si el PC está dormido y la acción no es WOL, sugerir "enciende el PC" primero.
- Las acciones HIGH (borrar, winget, PowerShell, apagar/reiniciar/suspender) SIEMPRE comprueban modo seguro primero.
