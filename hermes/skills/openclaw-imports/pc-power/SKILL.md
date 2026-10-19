---
name: pc-power
description: Apaga o suspende el PC fijo por el canal hub (con confirmación)
metadata:
  {
    "openclaw":
      {
        "requires": { "bins": ["python"], "os": ["win32"] },
      },
  }
---

# Energía del PC (apagar / suspender)

## Apagar

Cuando el usuario pida apagar el PC fijo ("apaga el PC"):

1. Pregunta primero: "¿Apago el PC fijo? Responde sí para confirmar."
2. Solo si el usuario responde sí explícito, ejecuta:

```text
python {{WIN_HOME}}\jarvis2\scripts\pc_power.py shutdown --yes
```

3. Informa el RESULTADO en una frase.

Capas de seguridad (no las saltes):

- Sin "sí" explícito no se ejecuta nada.
- El script exige `--yes`, mina un grant firmado de 60 s y un solo uso, y
  respeta el ratelimit del repo (máx. 10/min).
- Nunca muestres secretos (el script no los imprime).

## Suspender

"Suspende el PC" **no está disponible**: el canal hub no tiene manifiesto
`system.suspend` y el script lo rechaza (exit 3). Explícalo en una frase y
ofrece apagar en su lugar. El diseño para implementarlo en el PC está en
`{{WIN_HOME}}\jarvis2\docs\fase3b.md` (requiere cambio en el PC, no lo
implementes tú).
