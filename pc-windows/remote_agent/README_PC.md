JARVIS remote_agent: cliente saliente hacia el hub (no abre puertos).
Requiere Python 3.10+ y `pip install websockets`.
1. Copia esta carpeta al PC.
2. Copia .env.example a .env y pega el secreto.
3. Ejecuta: python agent.py
4. El agente reconecta solo con backoff.
Sin TLS el trafico va firmado (HMAC) pero NO cifrado.
Lee AGENTS.md para el detalle del protocolo jr_*.
