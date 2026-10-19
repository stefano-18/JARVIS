# JARVIS — Guía de inicio rápido (Día 5)

Sistema en dos nodos:

| Nodo | Rol | Carpeta |
|------|-----|---------|
| **Laptop** | Cerebro (Telegram, OpenRouter, Whisper, WOL, n8n, Obsidian) | `jarvis-server/` |
| **PC fijo** | HUD fullscreen + micrófono + control local de energía | `jarvis-ui/` |

---

## Requisitos previos

### Laptop

- Windows 10/11 con Python **3.10+**
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (opcional, para n8n)
- Bot de Telegram, clave [OpenRouter](https://openrouter.ai/)
- MAC del PC fijo para Wake-on-LAN (`PC_FIXED_MAC` en `.env`)

### PC fijo

- Windows 11
- Python **3.10+**, Node.js **LTS**
- Micrófono
- En **BIOS/UEFI**: Wake-on-LAN habilitado
- En el adaptador Ethernet (Propiedades → Avanzado): **Wake on Magic Packet** = Activado

---

## Instalación 1-Clic

### Laptop

```powershell
cd C:\Users\TuUsuario\jarvis-server
Set-ExecutionPolicy -Scope Process Bypass
.\install_laptop.ps1
```

Luego edita `.env`:

```env
TELEGRAM_BOT_TOKEN=...
TELEGRAM_AUTHORIZED_CHAT_ID=...
OPENROUTER_API_KEY=...
PC_FIXED_MAC=AA:BB:CC:DD:EE:FF
```

### PC fijo

```powershell
cd C:\Users\TuUsuario\jarvis-ui
Set-ExecutionPolicy -Scope Process Bypass
.\install_pc.ps1
```

Edita `.env.agent` y pon la IP de la laptop:

```env
JARVIS_WS_URL=ws://192.168.1.XXX:8765
```

---

## Encender ambos nodos (orden recomendado)

### 1. Laptop — WebSocket (terminal 1)

```powershell
cd jarvis-server
.\.venv\Scripts\Activate.ps1
python -m core.websocket_server
```

Debe mostrar: `JARVIS WebSocket listening on ws://0.0.0.0:8765`

> Abre el firewall de Windows para el puerto **8765** en la red local si el PC fijo no conecta.

### 2. Laptop — Bot Telegram + scheduler (terminal 2)

```powershell
cd jarvis-server
.\.venv\Scripts\Activate.ps1
python main.py
```

Opcional: enlaza voz con el cerebro usando `core.assistant_bridge.attach_brain` y `brain.handle_user_message` en un script de arranque unificado.

### 3. PC fijo — HUD (terminal 3 o acceso directo)

```powershell
cd jarvis-ui
npm start
```

O doble clic en **JARVIS HUD** en el escritorio.

### 4. PC fijo — Agente de voz y energía (terminal 4 o acceso directo)

```powershell
cd jarvis-ui
.\.venv-agent\Scripts\python.exe agent\pc_control.py
```

O **JARVIS Agente Voz** en el escritorio.

Flujo: *"Hey Jarvis"* → grabación → si dices **apaga / reinicia / bloquea el PC**, se ejecuta en local; si no, el audio va a la laptop (Whisper + respuesta TTS en el HUD).

---

## Probar funciones del Día 5

### Wake-on-LAN (desde la laptop)

1. Apaga el PC fijo (o déjalo en suspensión con WOL activo).
2. Por Telegram (o voz procesada en el cerebro): *"Enciende el PC"*, *"Prende el ordenador"*.
3. Jarvis usa la herramienta `wake_on_lan` con la MAC de `.env`.

Comprobación manual:

```powershell
cd jarvis-server
.\.venv\Scripts\Activate.ps1
python -c "from tools.wol import wake_on_lan; print(wake_on_lan())"
```

### Apagado / reinicio / bloqueo por voz (PC fijo)

Con el agente `pc_control.py` en marcha, tras la wake word:

| Frase (ejemplos) | Acción |
|------------------|--------|
| "Apaga el PC" | `shutdown /s /t 5` |
| "Reinicia el ordenador" | `shutdown /r /t 5` |
| "Bloquea la pantalla" | `LockWorkStation` |

Prueba sin micrófono:

```powershell
.\.venv-agent\Scripts\python.exe agent\pc_control.py --text "bloquea la pantalla"
```

### n8n (laptop)

Tras `install_laptop.ps1`: [http://localhost:5678](http://localhost:5678)

### Reporte matinal 07:00 (laptop)

Con `main.py` en ejecución, el `scheduler` (Día 4) dispara el reporte si está configurado Obsidian/Open-Meteo en `.env`.

---

## Variables de entorno útiles

| Variable | Dónde | Uso |
|----------|-------|-----|
| `PC_FIXED_MAC` | laptop `.env` | WOL |
| `WOL_BROADCAST` | laptop `.env` | Subred (p. ej. `192.168.1.255`) |
| `JARVIS_WS_URL` | PC `.env.agent` | URL del WebSocket de la laptop |
| `JARVIS_SHUTDOWN_DELAY` | PC | Segundos antes de apagar/reiniciar (default 5) |

---

## Solución de problemas

| Síntoma | Qué revisar |
|---------|-------------|
| PC fijo no enciende con WOL | BIOS WOL, cable Ethernet (no Wi‑Fi), MAC correcta, mismo switch/VLAN |
| Agente no conecta al WS | IP en `.env.agent`, firewall puerto 8765, `websocket_server` en la laptop |
| PyAudio falla en install | `pip install pipwin` → `pipwin install pyaudio` |
| SAPI no transcribe | Idioma es-ES en Windows; habla claro tras "Hey Jarvis" |
| HUD negro/transparente | `npm start` en PC fijo; resolución y drivers gráficos |

---

## Arquitectura (resumen)

```text
[Laptop jarvis-server]
  main.py (Telegram) ──► brain.py ──► tools (web, PS, Obsidian, wol.py)
  core.websocket_server :8765 ◄──► Whisper / TTS / HUD

[PC fijo jarvis-ui]
  Electron HUD ◄── WebSocket broadcast
  agent/pc_control.py ── mic + WOL N/A + shutdown/lock local
```

Cuando todo está en verde: Telegram o voz en el PC fijo controlan Jarvis; la laptop puede despertar el PC fijo por WOL; el PC fijo puede apagarse, reiniciarse o bloquearse por voz sin pasar por la nube.
