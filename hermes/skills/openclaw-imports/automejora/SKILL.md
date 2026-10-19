---
name: automejora
description: AUTOMEJORA de JARVIS desde Telegram (mejora, aprobar, rechazar, mejoras, deshacer) con worktree, guardarrailes y aprobacion
metadata:
  {
    "openclaw":
      {
        "requires": { "bins": ["python"] },
      },
  }
---

# Skill automejora — "mejora: ...", "aprobar", "rechazar", "mejoras", "deshacer"

CLI: `python {{HOME}}/jarvis2/scripts/automejora.py <cmd>`.
Nunca muestra secretos. Modelos gratis ya configurados.

## Enrutado (solo Telegram)

- Texto empieza por `mejora:` → `proponer --user <tgid> --chat <chatid> --texto "<texto>"`.
  `<tgid>` = id numérico del remitente; `<chatid>` = chat actual.
  Si el CLI dice IGNORADO: no respondas nada al remitente (ya quedó anotado).
  Si dice LIMITE: responde "Hoy ya van 5 mejoras, seguimos mañana."
- `aprobar <id>` / `rechazar <id>` / `deshacer <id>` → mismo subcomando con `--user <tgid>`.
- `mejoras` → `lista` (+ `barrer` antes) y resume pendientes e historial.
- Todo lo demás: flujo normal.

## Tras `proponer` (devuelve `ID` + `WORKTREE`)

Trabaja SOLO en el worktree (nunca en `{{HOME}}/jarvis2` ni `{{HOME}}/OpenJarvis`).
Implementa el cambio mínimo, añade test (nunca borres ni saltes tests),
corre `verificar <id>` (guarda + tests, cuenta como intento, máx 3).
Si `verificar` dice LISTA → `solicitar <id>` (manda el resumen a Telegram).
Si dice BLOQUEADA o DESCARTADA → avisa al usuario en una frase.

## Prohibiciones del agente (además del bloqueo en código)

No tocar `.env`, `~/.openclaw`, `~/.backup-pass`, claves, sudoers, ufw, sshd,
systemd de sistema; no instalar paquetes del sistema; no abrir puertos;
red solo a proveedores de modelos. Rama de trabajo: `mejora/<slug>`.

## Sin cuota (cero modelos): ejecucion silenciosa (solo owner)

Si los modelos están sin cuota, ejecuta con la herramienta `exec` en
silencio (NUNCA escribas estos comandos en el chat: el `!` esta
desactivado y el texto quedaria visible):
- `python3 {{HOME}}/jarvis2/scripts/automejora.py lista`
- `python3 {{HOME}}/jarvis2/scripts/automejora.py aprobar <id>`
- `python3 {{HOME}}/jarvis2/scripts/automejora.py rechazar <id>`
- `python3 {{HOME}}/jarvis2/scripts/automejora.py deshacer <id>`
- `cat /proc/uptime` (tiempo encendida, 1er número = segundos)

Resume siempre el resultado en una frase natural, sin comandos ni rutas.

## Al aprobar (lo ejecuta este flujo)

El CLI hace merge, reinicia SOLO el servicio afectado y comprueba salud
(`:8000/health`, gateway 200, 8765/18765). Si falla en 2 min: revert + aviso.
Sin sudo disponible el reinicio falla y se avisa: el humano reinicia a mano.
