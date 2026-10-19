---
name: wake-pc
description: Despierta el PC fijo por Wake-on-LAN y espera a que responda al ping
metadata:
  {
    "openclaw":
      {
        "requires": { "bins": ["python"], "os": ["win32"] },
      },
  }
---

# Despertar PC (Wake-on-LAN)

Cuando el usuario pida encender o despertar el PC fijo (ejemplos: "enciende
el PC", "despierta el PC", "wake"), ejecuta el script del repo jarvis2:

```text
python {{WIN_HOME}}\jarvis2\scripts\wake_pc.py
```

Comportamiento del script (no lo reimplementes, solo ejecútalo):

- Si el PC ya está despierto (ping o TCP 11434/8765 en {{PC_IP}}),
  informa de que ya está despierto y no envía nada.
- Si no responde, envía el magic packet a la MAC guardada en `JARVIS_PC_MAC`
  (broadcast {{RED}}.255, puertos 9 y 7) y espera hasta 120 s a ping o TCP.
- Exit 0 = despierto. Exit 1 = timeout o inalcanzable. Exit 2 = MAC mal
  configurada.

Cuando el script diga que el PC está despierto (ya lo estaba o acaba de
despertar), verifica Ollama con:

```text
curl.exe -s -m 10 http://{{PC_IP}}:11434/api/tags
```

- Si `/api/tags` responde, contesta al usuario: "PC encendido, Ollama listo".
- Si no responde pero el PC sí (ping/TCP), contesta: "PC encendido, pero
  Ollama no responde (revisa OLLAMA_HOST en el PC)".

Reglas:

- Informa al usuario con el RESULTADO del script, en una frase.
- Nunca muestres la MAC completa (el script ya la redacta).
- No modifiques `JARVIS_PC_MAC` ni `PC_IP`; viven en `jarvis2/.env`.
- Si el resultado es timeout, sugiere revisar WOL en BIOS, suspensión
  híbrida y que el PC esté cableado a la misma LAN.
