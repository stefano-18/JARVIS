---
name: estado
description: Estado de laptop, PC y modelo de IA en una respuesta corta
metadata:
  {
    "openclaw":
      {
        "requires": { "bins": ["python"], "os": ["win32"] },
      },
  }
---

# Estado del sistema

Cuando el usuario pida el estado ("estado", "cómo estás", "cómo va todo"),
ejecuta:

```text
python {{WIN_HOME}}\jarvis2\scripts\estado.py
```

Resume su salida en 3-4 líneas: laptop (CPU/RAM/disco/uptime), servicios
(gateway, Ollama, hub), PC (encendido/apagado, Ollama, modelo en memoria) y
qué modelo de IA está respondiendo. No añadas datos que el script no dé.
