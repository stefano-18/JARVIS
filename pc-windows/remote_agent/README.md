# agent_pc — Remote Agent (jarvis2, PC fijo)

Solo Windows. Ejecutar SOLO en tu propia maquina. Nunca en equipos ajenos.
Cliente saliente hacia el hub (no abre puertos). Requiere Python 3.10+.

## Instalacion (sin admin)

```powershell
powershell -ExecutionPolicy Bypass -File install_agent.ps1 -SharedSecret "pega-aqui-el-secreto-del-hub" -HubHost "IP-del-hub" -DeviceId "pc-amigo-01"
```

- Crea `.venv` e instala dependencias (usuario actual, sin elevar, sin `schtasks`).
- Escribe `.env` en UTF-8 sin BOM. El secreto debe coincidir EXACTAMENTE con el del hub; aqui no se genera.
- Crea la carpeta de `ROOTS` y registra arranque automatico con `JarvisRemoteAgent.vbs` en tu `Startup` (pythonw oculto, idempotente: chequeo WMI + `agent.lock` con PID).
- Arranque manual: `.\.venv\Scripts\pythonw.exe agent.py` (o doble clic al VBS).

Copia `.env.example` a `.env` si prefieres rellenar a mano. Nunca subas `.env` al repo.

## Acciones

| Accion | Riesgo | Que hace |
|---|---|---|
| `system.info` | LOW | CPU/RAM/disco/GPU/temp (solo lectura) |
| `process.list`, `process.info` | LOW | Enumerar / detalle de procesos |
| `files.list`, `files.search`, `files.read` | LOW | Listar/buscar/leer (sin restriccion de roots en LOW, pero `write/copy/move` si la exigen) |
| `window.list` | LOW | Enumerar ventanas |
| `tasks.stub` | LOW | Reservado, no implementado |
| `shell.exec` (en allowlist `COMMANDS`) | LOW | Ejecuta comando permitido, sin shell, con timeout y tope 64 KB |
| `apps.open`, `apps.close` | MEDIUM | Abrir/cerrar solo apps de la allowlist `APPS` (deteccion por instantaneas; cierre solo de lo propio, o `force=true` por imagen exacta) |
| `files.write`, `files.copy`, `files.move` | MEDIUM | Escribir/copiar/mover SOLO dentro de `ROOTS` |
| `shell.exec` (fuera de allowlist) | HIGH (escalado) | Exige concesion firmada |
| `files.delete` | HIGH | No borra: mueve a cuarentena `_jarvis_trash` dentro de un root. Exige concesion |
| `process.terminate` | HIGH | Matar proceso. Exige concesion |
| `system.shutdown`, `system.restart`, `system.lock`, `system.logoff` | HIGH | Energia/sesion. Solo `ok` si el SO lo acepto. Exige concesion |
| `screen.capture`, `window.focus/minimize/maximize/move`, `ui.click`, `ui.keypress`, `clipboard.read/write` | HIGH | Computer use. Exige concesion |

## Niveles de riesgo

- **LOW**: directo, sin concesion.
- **MEDIUM**: solo dentro de su ambito (`ROOTS` / `APPS` / `COMMANDS`). Fuera de ambito se deniega con `executed=false` (nunca se afirma exito).
- **HIGH**: exige concesion firmada del hub (60 s, un solo uso, ligada a accion+parametros). Sin grant valido se deniega. Limite local deslizante (`HIGH_MAX_PER_MINUTE`/`HIGH_MAX_PER_HOUR`, defecto 10/60): al superar, error `high_rate_limited` con segundos de espera. Todo queda en `audit.jsonl` (cadena de hashes).

## Kill switch

- `killswitch.json` con `{"locked": true}` bloquea TODA accion MEDIUM/HIGH; las LOW siguen. No mata procesos ni apaga nada. El agente lo lee en cada decision: surte efecto sin reiniciar y sobrevive a reinicios.
- Bloqueo remoto: mensaje firmado `jr_killswitch`. Desbloqueo remoto: `jr_unlock` + grant HIGH de un solo uso para `agent.unlock`.
- Detalle completo en `README_KILLSWITCH.md`.

## Desbloqueo local (emergencia, presencia fisica)

1. Doble clic en `scripts\unlock_local.bat` (o `python scripts\unlock_local.py`).
2. Escribe `DESBLOQUEAR` cuando lo pida.
3. Restaura `killswitch.json` a desbloqueado SIN reiniciar; queda registrado en `killswitch_local.log`, sin tocar `audit.jsonl`.

## Anadir apps

En `.env`: `APPS=notepad=notepad.exe;calc=calc.exe;miapp=%LOCALAPPDATA%\Programs\MiApp\app.exe`. Usa variables (`%LOCALAPPDATA%`, `%APPDATA%`, `%USERPROFILE%`), nunca rutas con tu nombre de usuario. Prueba con `apps.open`/`apps.close` antes de usarla en serio.
