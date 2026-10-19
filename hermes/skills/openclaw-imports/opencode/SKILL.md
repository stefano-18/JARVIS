---
name: opencode
description: Ejecuta tareas con OpenCode (CLI) desde Telegram. "opencode: <tarea>" lanza en {{HOME}}/tareas, máx 30 min, resumen por Telegram.
metadata:
  {
    "openclaw":
      {
        "requires": { "bins": ["opencode"] },
      },
  }
---

# OpenCode desde Telegram ("opencode: <tarea>")

Cuando el mensaje empieza por `opencode:`, ejecuta la tarea con OpenCode CLI.

## Flujo

1. Extrae el texto después de `opencode:`.
2. Ejecuta (no interactivo, timeout 30 min):

```bash
cd {{HOME}}/tareas && opencode run "<tarea>" --timeout 1800
```

3. Al terminar, resume el resultado en 3-4 líneas por Telegram:
   - ¿Qué se hizo?
   - Archivos creados/modificados
   - Tests pasados/fallados
   - Commit (si aplica)

## Reglas

- Usuario: `{{USUARIO}}`. Directorio de trabajo: `{{HOME}}/tareas`.
- Timeout máximo: 30 minutos (1800 s). Si excede, avisa.
- Si la tarea requiere root, solo permite si `/etc/sudoers.d/92-jarvis-apt` existe y contiene la regla.
- Nunca muestres tokens, claves, ni contenido de `.env`.
- Si `opencode run` falla, reporta el error sin detalles sensibles.
