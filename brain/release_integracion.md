# agent_pc — integración laptop ↔ PC (código real incluido)

El código real del PC vive en `agent_pc/` de este repo (integrado desde
`_incoming/agent_pc.zip` con `scripts/make_release.py`; detalle del agente
en `agent_pc/README.md`).
El espejo del lado laptop es `remote_agent/` (stubs con `fn=None` para
computer-use; nunca ejecuta HIGH en local, solo envía `jr_req` al PC).

## Cómo incorporarlo

1. En la laptop: `python scripts/setup.py` (genera `JARVIS_REMOTE_SECRET`
   en `.env`, sin mostrarlo).
2. El PC ya está en `agent_pc/` (no hace falta copiar `remote_agent/`;
   se conserva por compatibilidad con el hub). Para llevarlo al PC usa
   USB o repo privado, p. ej. `C:\JARVIS-PC\agent_pc`.
3. En el PC: copia `agent_pc/.env.example` a `agent_pc/.env` y pega
   `HUB_HOST` (IP/Tailscale de la laptop), `HUB_PORT=18765`,
   `DEVICE_ID` y `SECRET` (el mismo `JARVIS_REMOTE_SECRET` de la laptop).
   Ajusta `ROOTS/APPS/COMMANDS` a lo que permitas en ese PC.
4. En el PC (Python 3.11/12, sin admin):
   `pip install websockets` y `python agent.py` (reconecta solo con backoff).
   Alternativa instalada: `install_agent.ps1` (ver `agent_pc/README.md`).
   Para tests del agente: `pip install websockets pytest psutil mss Pillow
   pywin32` (ver `install_agent.ps1`); sin `mss/Pillow/pywin32` la captura
   y ventanas devuelven error honesto y 3 tests de `agent_pc/tests`
   fallan en la laptop.
   Nota laptop: `requirements.txt` fija `numpy>=1.26,<2` porque la serie 2.x
   queda bloqueada por Control de aplicaciones (`_multiarray_umath`).
5. En la laptop: arranca `python scripts/hub_service.py` y comprueba
   `logs/remote_audit.jsonl` (`agent.hello` del `DEVICE_ID`).
6. Sincronía: corre `python agent_pc/verify_sync.py --pc-path agent_pc`
   (o `--pc-path C:\JARVIS-PC\agent_pc` para la copia viva del PC;
   sin args compara contra `remote_agent/` local). Debe decir SYNC OK;
   si difieren manifiestos/riesgos, el lado desactualizado es la laptop:
   corrige solo `remote_agent/` y no toques `agent_pc/` salvo error
   evidente (ver `agent_pc/README.md` para el detalle del PC).

Nunca commitees el `.env` del PC ni `audit.jsonl`/`killswitch.json`.
