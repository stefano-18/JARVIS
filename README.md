# JARVIS

[![CI](https://github.com/stefano-18/JARVIS/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/stefano-18/JARVIS/actions/workflows/ci.yml)

**Un asistente personal por voz y Telegram.** Dile «Hey Jarvis» o escríbele por Telegram: abre apps y juegos, mueve ventanas entre pantallas, pone música, hace capturas, te recuerda cosas y te contesta con su propia voz.

Un **cerebro** en un portátil Linux (Python + [Hermes](https://github.com/NousResearch) + Claude Haiku) controla tu **PC** (Linux con Omarchy/Hyprland, o Windows) mediante un agente que se conecta solo al arrancar. Lo delicado - apagar, borrar, instalar, enviar - siempre pide tu palabra clave.

> Lo simple no gasta IA: «abre Spotify», «volumen al 40» o «apaga el PC» se resuelven al momento por una vía rápida sin modelo. Solo lo que necesita pensar llega a Claude, con caché de prompts y tope de gasto diario.

```
«Hey Jarvis, abre Phasmophobia»          # voz en el PC
«resúmeme este enlace»                     # Telegram
«apaga el PC»                              # pide la palabra clave
```

```
jarvis-repo/
├── brain/        cerebro (Linux): voz, Telegram, juegos, pantallas, órdenes al PC
├── hermes/       personalidad (SOUL.md), filtro de órdenes rápidas y skills
├── pc-windows/   agente y voz del PC (Linux en linux/ y actions_linux.py, Windows en .ps1)
├── services/     unidades systemd del portátil y del PC Linux
├── config/       ejemplos sin claves (env.example, config.toml.example)
├── tools/        anonimizar, rellenar marcadores, actualizar el repo
├── tests/        pruebas
└── docs/         guías y pendientes
```

## Instalación

**Requiere:** un portátil, servidor o PC con Linux (Ubuntu/Lubuntu o Arch/Omarchy), Python 3.11+ y Node 18+. Tus propias claves de Anthropic (Claude Haiku), un bot de Telegram, Groq (para oír) y, si quieres, Google (calendario y Gmail).

**1. El cerebro (portátil Linux)**

```bash
git clone https://github.com/stefano-18/JARVIS.git ~/jarvis-repo && cd ~/jarvis-repo
python3 setup.py           # pregunta tus datos y claves (solo en este equipo, permisos 600)
./install.sh --dry-run     # enseña qué va a hacer, sin tocar nada
./install.sh
```

**2. El PC con Linux (Omarchy / Arch + Hyprland)**

```bash
git clone https://github.com/stefano-18/JARVIS.git ~/jarvis-repo && cd ~/jarvis-repo
bash pc-windows/linux/instalar-pc-linux.sh <IP-del-portátil> --simulacion   # enseña qué va a hacer
bash pc-windows/linux/instalar-pc-linux.sh <IP-del-portátil>                # pide el secreto del hub
```

**2b. O el PC con Windows** - en PowerShell, sin administrador:

```powershell
.\pc-windows\instalar-pc.ps1 -Portatil <IP-del-portátil> -Simulacion   # enseña qué va a hacer
.\pc-windows\instalar-pc.ps1 -Portatil <IP-del-portátil>
```

**3. O instalación completa (Linux)** - JARVIS entero, cerebro y cuerpo, en el mismo equipo. Es la opción más sencilla si solo tienes un ordenador: el cerebro, el control del PC y la voz se hablan por `127.0.0.1`, sin SSH ni red entre máquinas y sin nada abierto hacia fuera.

```bash
git clone https://github.com/stefano-18/JARVIS.git ~/jarvis-repo && cd ~/jarvis-repo
python3 setup.py --completa                          # tus datos y claves; las IP ya van a 127.0.0.1
./install.sh                                         # el cerebro
bash pc-windows/linux/instalar-pc-linux.sh 127.0.0.1 # control del PC y voz; coge el secreto solo
```

> **La instalación completa solo funciona en Linux** (pensado para Omarchy / Arch + Hyprland). En Windows el cerebro no corre: ahí hacen falta dos equipos (pasos 1 y 2b).
> **Es la opción más nueva:** cada pieza está probada en Linux, pero juntas en un mismo equipo aún no se han probado en una instalación desde cero. Si algo falla, `pc_do.py status` y el registro del agente dicen dónde.
> **Si apagas ese PC, JARVIS se apaga con él** - Telegram deja de contestar hasta que lo enciendas. Con un portátil aparte (pasos 1 y 2) el cerebro sigue despierto y puede encender el PC a distancia.

Luego escríbele a tu bot de Telegram:

```
abre Spotify
```

> **Las claves nunca van al repositorio.** Las pide `setup.py` en tu propio equipo (ver `config/*.example`). Los datos personales - IPs, chat de Telegram, cuentas, rutas - están en el código como marcadores `{{...}}` que `install.sh` rellena con tu `config.toml`.
> **Fija la IP del portátil** en tu router (en una FRITZ!Box: «usar siempre esta dirección IP»). El agente del PC se conecta a esa IP; si cambia, las órdenes no llegan.
> **Palabra clave:** se pone con `jarvis_gate.py`. Sin ella, apagar, reiniciar o suspender no se ejecutan.

<details>
<summary>Instalación manual del PC Linux</summary>

```bash
sudo pacman -S --needed python grim slurp wtype ydotool wl-clipboard playerctl portaudio jq
systemctl --user enable --now ydotool.service
python3 -m venv ~/.local/share/jarvis/venv-voz
~/.local/share/jarvis/venv-voz/bin/pip install websockets psutil requests numpy edge-tts sherpa-onnx openwakeword pyaudio
```

Crea `~/.config/jarvis-pc/agent.env` (permisos 600):

```
DEVICE_ID=pc-01
SECRET=<el JARVIS_REMOTE_SECRET del portátil>
HUB_HOST=<IP-del-portátil>
HUB_PORT=18765
SCREEN_C1=1
MEDIA_VOLUME=1
ROOTS=/home/<tu-usuario>
YDOTOOL_SOCKET=/tmp/.ydotool_socket
```

Copia `services/pc-linux/*.service` a `~/.config/systemd/user/` (cambia `{{PORTATIL_IP}}` por la IP del portátil) y:

```bash
systemctl --user daemon-reload
systemctl --user enable --now jarvis-agente.service jarvis-voz.service
tail -f ~/jarvis-repo/pc-windows/remote_agent/logs/remote_agent.log   # debe decir «Conectado y autenticado»
```

</details>

## Comprobar que funciona

```bash
python3 tests/test_basico.py                    # en el portátil
python3 ~/jarvis2/scripts/pc_do.py status       # "agente": true = el PC recibe órdenes
python3 ~/jarvis2/scripts/pc_do.py open pinta   # abre una app en el PC de verdad
```

| Si JARVIS dice... | Qué pasa | Qué hacer |
|---|---|---|
| «No llego al PC» | el agente del PC no está conectado al cerebro | mira que los dos estén en la misma red y la IP del portátil no haya cambiado |
| «Esto necesita su palabra clave» | orden delicada | dila por voz o por Telegram |
| «No he podido abrir X» | X no está instalada en el PC | comprueba el nombre; la lista sale de las apps y juegos instalados |

## Qué hace

- **Voz en el PC** - «Hey Jarvis»: abre y cierra apps y juegos (Steam, Heroic, Epic), mueve ventanas entre las dos pantallas, volumen y música.
- **Nombres mal oídos** - compara cómo *suenan* las palabras: «Fasmofobia» es *Phasmophobia*, «espotifai» es *Spotify*. Y aprende a pronunciar bien cada nombre la primera vez que aparece.
- **Telegram** - charla con memoria, recordatorios, resumen de la mañana, capturas, notas de voz, «resúmeme este enlace».
- **Departamentos a demanda** - correo (solo borradores), investigador (tareas largas con entrega a una hora), programador, mejora continua (propone y solo aplica con tu «sí») y seguridad.
- **Seguro** - lo delicado exige tu palabra clave o tu visto bueno; las claves viven solo en tu equipo.
- **Barato** - vía rápida sin IA para lo simple, caché de prompts, tope de gasto diario.

Omarchy y PC con Linux, con detalle: [docs/OMARCHY.md](docs/OMARCHY.md). Qué ha cambiado: [docs/CAMBIOS.md](docs/CAMBIOS.md).

<details>
<summary>English</summary>

**A personal voice + Telegram assistant.** A Python **brain** on a Linux laptop (Hermes + Claude Haiku) drives your **PC** (Linux with Omarchy/Hyprland, or Windows) through an agent: apps, Steam/Heroic/Epic games, windows across both screens, volume, music, screenshots - and answers with its own Spanish voice. Sensitive actions need your passphrase.

**Install** - brain: `python3 setup.py`, `./install.sh --dry-run`, `./install.sh`. Linux PC: `bash pc-windows/linux/instalar-pc-linux.sh <laptop IP>`. Windows PC: `.\pc-windows\instalar-pc.ps1 -Portatil <laptop IP>`. Keys never go in the repo: see `config/env.example` and `config/config.toml.example`.

</details>

## Licencia

MIT (provisional, ver [LICENSE](LICENSE)).
