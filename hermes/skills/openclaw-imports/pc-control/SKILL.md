---
name: pc-control
description: Controla el PC fijo por el canal hub (abrir/cerrar apps, bloquear, suspender, apagar, reiniciar, enviar archivos, modo juego)
metadata:
  {
    "openclaw":
      {
        "requires": { "bins": ["python"], "os": ["win32"] },
      },
  }
---

# Control del PC fijo (canal hub, Fase 5)

Runner: `python {{WIN_HOME}}\jarvis2\scripts\pc_do.py <cmd>`. Nunca muestra secretos.

## Órdenes directas (sin confirmación)

- "abre X en el PC" → `pc_do.py open X` (ej.: `open Spotify`, `open notepad`)
- "cierra X en el PC" → `pc_do.py close X`
- "bloquea el PC" → `pc_do.py lock`
- "manda este archivo al PC" → guarda el adjunto en local y `pc_do.py sendfile <local> <nombre-archivo>` (el script antepone `{{WIN_HOME}}\Desktop\JARVIS-recibidos\`, única ruta que acepta el agente). NOTA 2026-10-15: confirmado que llega sin confirmación.
- "cómo está el PC" → `pc_do.py status`

Informa el RESULTADO en una frase.

## Energía (piden "sí" explícito)

- "suspende el PC" → pregunta "¿Suspendo el PC fijo? Responde sí para confirmar." Solo con sí: `pc_do.py suspend --yes`
- "apaga el PC" → igual, `pc_do.py shutdown --yes`
- "reinicia el PC" → igual, `pc_do.py restart --yes`

Sin "sí" explícito no se ejecuta nada. Si el PC está dormido, primero `pc_do.py ensure-awake` (WOL + espera 90 s) y luego la orden.

## Modo juego

- "Jarvis, voy a jugar" → `pc_do.py game on`. Confirma: "Modo juego activado."
- "Jarvis, terminé" → `pc_do.py game off`. Confirma: "Modo juego desactivado."
- Con modo juego activo, NUNCA uses el PC para IA (ni WOL); usa ollama local.
