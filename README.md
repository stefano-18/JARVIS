# JARVIS

**Español** · [English](#english)

Asistente personal por voz y Telegram: un **cerebro** en un portátil Linux (Python + [Hermes](https://github.com/NousResearch) +
Claude Haiku) que controla un **PC con Windows** (ratón, teclado, pantallas, apps y juegos de Steam/Epic) mediante un agente,
y que te habla con su propia voz.

## Qué hace
- Voz en el PC («Hey Jarvis»): abre y cierra apps y juegos y se mueve por las dos pantallas.

### Nombres mal pronunciados o mal oídos
JARVIS compara cómo **suenan** las palabras, no solo cómo se escriben. Por ejemplo, «Fasmofobia» o «farmofobia» los
reconoce como *Phasmophobia*, y «espotifai» como *Spotify*. Si aun así no está seguro, deduce con IA qué se quiso decir
en lugar de pedir que se repita. Además aprende a **pronunciar** bien los nombres de juegos y aplicaciones: guarda cómo se
dice cada uno la primera vez que aparece, y desde entonces lo dice correctamente.
- Telegram: charla con memoria, recordatorios, resumen de la mañana, capturas de pantalla, notas de voz, «resúmeme este enlace».
- Departamentos **a demanda**: correo (solo borradores), investigador (tareas largas con entrega a una hora), programador,
  mejora continua (propone; solo aplica con tu «sí») y seguridad (informe de vulnerabilidades).
- Lo delicado (apagar, borrar, instalar, enviar) exige tu palabra clave o tu visto bueno.
- Ahorro: respuestas sin IA para lo simple, caché de prompts, tope de gasto diario.

## Requisitos
- Portátil o servidor con **Linux** (Ubuntu/Lubuntu o Arch/Omarchy), Python 3.11+, Node 18+.
- PC con **Windows 10/11** y Python 3.11+ para el agente y la voz (opcional: sin él funcionan Telegram y el cerebro).
- Claves propias: Anthropic (Claude Haiku), bot de Telegram, Groq (solo para oír) y Google (calendario y Gmail, opcional).

## Instalación
**Linux (cerebro):**
```bash
git clone <tu-repo> ~/jarvis-repo && cd ~/jarvis-repo
python3 setup.py         # pregunta sus datos y claves (solo en este equipo, permisos 600)
./install.sh --dry-run   # muestra qué hará
./install.sh
```
**Windows (PC):** en PowerShell, sin administrador:
```powershell
.\pc-windows\instalar-pc.ps1 -Portatil <IP-del-portátil> -Simulacion   # muestra qué hará
.\pc-windows\instalar-pc.ps1 -Portatil <IP-del-portátil>
```
**Claves:** las pide `setup.py` en su propio equipo y nunca van al repositorio (ver `config/*.example`). Los datos personales
(IPs, chat de Telegram, cuentas, rutas) están en el código como marcadores `{{...}}` que `install.sh` rellena con su
`config.toml`. La palabra clave se pone con `jarvis_gate.py`. Comprobación: `jx_autotest.py` y `python3 tests/test_basico.py`.

## Carpetas
`brain/` cerebro (Linux) · `hermes/` personalidad, filtro y skills · `pc-windows/` agente y voz del PC · `services/`
unidades systemd · `config/` ejemplos sin claves · `tools/` anonimizar/rellenar · `tests/` pruebas · `docs/` guías y pendientes

Omarchy y PC con Linux: ver [docs/OMARCHY.md](docs/OMARCHY.md).

## Licencia
MIT (provisional, ver LICENSE).

---

## English

Personal voice + Telegram assistant: a Python **brain** on a Linux laptop (Hermes + Claude Haiku) that drives a **Windows PC**
(mouse, keyboard, both screens, apps, Steam/Epic games) through an agent, with its own Spanish voice.

**Misheard or mispronounced names:** JARVIS compares how words *sound*, not only how they are spelled — "Fasmofobia" or
"farmofobia" become *Phasmophobia*, "espotifai" becomes *Spotify*. If it is still unsure, it infers the intended word with AI
instead of asking you to repeat. It also learns to *pronounce* game and app names correctly: the first time a name appears it
stores how to say it, and from then on says it right.

**Features:** PC voice control; Telegram chat with memory, reminders, morning
briefing, screenshots, voice notes and link summaries; on-demand departments (mail drafts only, researcher with scheduled
delivery, programmer, continuous improvement that only applies changes after your "yes", security audit). Sensitive actions
need your passphrase or explicit approval. Token saving: local answers, prompt caching, daily spend cap.

**Requirements:** Linux (Ubuntu/Lubuntu or Arch/Omarchy) with Python 3.11+ and Node 18+; optional Windows 10/11 PC with
Python 3.11+; your own Anthropic, Telegram bot, Groq (speech-to-text) and optional Google keys.

**Install:** Linux: `python3 setup.py`, `./install.sh --dry-run`, then `./install.sh`. Windows: `pc-windows\instalar-pc.ps1 -Portatil <laptop IP>`.
Put your keys by hand (never in the repo): see `config/env.example` and `config/config.toml.example`.

**License:** MIT (provisional).
