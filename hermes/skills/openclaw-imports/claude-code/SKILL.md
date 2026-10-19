---
name: claude-code
description: Trabajos largos de programación o creación (webs, apps, scripts, documentos) que JARVIS deja haciéndose solo en la laptop con Claude Code y avisa al terminar.
metadata:
  {
    "openclaw":
      {
        "requires": { "bins": ["python3", "claude"], "os": ["linux"] },
      },
  }
---
# Trabajos largos con Claude Code
Úsalo cuando el usuario pida construir algo grande: "hazme una web de...", "móntame una app que...", "prepárame un script que...".
Ejecuta SIEMPRE con la herramienta `exec`, en silencio. Nunca escribas comandos, rutas ni JSON en el chat.
Runner: `/usr/bin/python3 {{HOME}}/jarvis2/scripts/cc_tarea.py`

| Lo que pide el usuario | Qué ejecutar |
|---|---|
| "hazme una web/app/... de X" | `nohup /usr/bin/python3 {{HOME}}/jarvis2/scripts/cc_tarea.py <nombre-corto> haiku "<encargo completo y detallado>" >/dev/null 2>&1 &` |
| lo mismo pero "con Sonnet" o "que sea muy completo" | igual pero `sonnet` en vez de `haiku` |
| "¿cómo va X?" | `/usr/bin/python3 {{HOME}}/jarvis2/scripts/cc_tarea.py estado <nombre-corto>` |
| "enséñame X" / "quiero verla" | `/usr/bin/python3 {{HOME}}/jarvis2/scripts/cc_tarea.py ver <nombre-corto>` y da el enlace que devuelve |

## Reglas
- Antes de lanzar, si el encargo es vago, haz UNA pregunta corta para concretar (estilo, secciones, para qué es). Si ya está claro, lánzalo directamente.
- Escribe el encargo para Claude Code completo y concreto: qué construir, contenido, estilo, que funcione en móvil, y en qué tecnología (por defecto HTML, CSS y JavaScript sin servidor).
- Por defecto usa `haiku`. Usa `sonnet` solo si el usuario lo pide o acepta, y avísale de que cuesta unas 20 veces más.
- Tras lanzarlo responde en una frase: "Me pongo con ello, señor. Le aviso cuando esté." El aviso de fin llega solo por Telegram.
- Nunca publiques nada en internet ni compres dominios o servicios sin que el usuario lo pida expresamente.
