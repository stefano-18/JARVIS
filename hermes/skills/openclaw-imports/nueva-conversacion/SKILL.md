---
name: nueva-conversacion
description: Inicia una conversación nueva vaciando el historial
metadata:
  {
    "openclaw":
      {
        "requires": { "bins": [], "os": ["linux"] },
      },
  }
---

# Nueva conversación

Cuando el usuario escriba **"nueva conversación"**, **"/nueva"**, **"nueva charla"** o **"empezar de nuevo"**, ejecuta inmediatamente:

```bash
openclaw agent --reset --session main
```

Si falla el reset directo, alternativa:

```bash
rm -f {{HOME}}/.openclaw/agents/main/agent/openclaw-agent.sqlite-wal
openclaw gateway restart
```

Después de ejecutar, confirma al usuario: *"Conversación nueva iniciada. Historial vacío."*
