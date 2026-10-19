# JARVIS en Omarchy (Arch + Hyprland)

Omarchy es Arch Linux con Hyprland (Wayland). Casi todo JARVIS es Python y servicios de usuario de systemd, así que
**el cerebro funciona tal cual**. Lo que hoy depende de Windows es la parte del PC (el agente y la voz).

## Funciona tal cual (copiar y ejecutar `install.sh`)

| Pieza | Por qué funciona |
|---|---|
| Cerebro (`~/jarvis2/scripts`, voz_cerebro, juegos, pantalla) | Python 3 puro + venv; `install.sh` detecta `pacman` |
| Hermes + plugin `jarvis-filtro` + SOUL.md | Hermes es Python; el plugin y las skills se copian |
| Telegram (bot, avisos, recordatorios, resumen) | Solo HTTPS |
| Agenda y técnico (`jarvis-agenda`, vigilante, autotest, copias) | Servicios de usuario de systemd (Arch usa systemd) |
| Pronunciación (`aprende_pron.py`, `jarvis-pron.timer`) | Python + timer de usuario |
| Google (calendario y Gmail) | `google-api-python-client` en el venv |

### Pasos
```bash
git clone <tu repo privado> ~/jarvis-repo && cd ~/jarvis-repo
python3 setup.py          # sus datos y claves
./install.sh --dry-run    # mira qué haría
./install.sh              # lo hace
```
Luego, a mano y nunca por chat: las claves (`~/jarvis2/.env`, `~/.config/jarvis/anthropic.key`, `~/.hermes/.env`),
la palabra clave (`jarvis_gate.py`) y `google_jx.py auth`.

El servidor de voz `jarvis-v2` es un servicio de **sistema** (escucha en el puerto 8765):
```bash
sudo cp services/sistema/jarvis-v2.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now jarvis-v2
```
Si quieres que JARVIS pueda reiniciarlo solo (el vigilante lo hace), añade con `sudo visudo` una línea que permita
**solo** `systemctl restart jarvis-v2` a tu usuario.

## Si el propio PC pasa a Omarchy (necesita versión Linux)

Hoy el PC es Windows: `remote_agent` (ratón, teclado, capturas, ventanas, apps) y `jarvis_voz` (micrófono y voz).
En Omarchy haría falta una versión Linux de cada acción. Equivalencias:

| Acción del agente | Windows hoy | Omarchy (Wayland/Hyprland) |
|---|---|---|
| `screen.capture` | mss / PIL | `grim` (y `grim -o <monitor>` por pantalla) |
| `ui.click`, mover ratón | SetCursorPos | `ydotool` (necesita el servicio `ydotoold`) |
| `ui.keypress`, escribir | SendInput | `wtype` (o `ydotool key`) |
| `window.list/focus/move` | win32gui | `hyprctl clients -j`, `hyprctl dispatch focuswindow`, `movewindowpixel` |
| `apps.open/close` | lista APPS + .vbs | `gtk-launch <app>.desktop` / `pkill`; la lista sale de `/usr/share/applications` |
| `volume.*`, `media.*` | pycaw | `wpctl set-volume @DEFAULT_SINK@ 60%`, `playerctl play-pause` |
| `system.lock/suspend` | Windows | `hyprlock`, `systemctl suspend` (siguen pidiendo la palabra clave) |
| Voz (micrófono, TTS edge) | PyAudio + edge-tts | PipeWire (`pw-record`/`sounddevice`) + edge-tts igual |
| Steam | Steam Windows | Steam nativo (`steam steam://rungameid/<id>` funciona igual) + Proton |
| Epic | Epic Launcher | **Heroic Games Launcher** (`heroic --no-gui ...`) |
| Encender el PC (WOL) | igual | igual (activar WOL en la BIOS y en NetworkManager) |

### Pasos para el agente Linux (cuando toque)
1. `sudo pacman -S grim slurp wtype ydotool playerctl` y `systemctl --user enable --now ydotool`.
2. Crear `remote_agent/actions_linux.py` con las mismas acciones y nombres que `actions_desktop.py`
   (el protocolo y el hub no cambian, así que el cerebro no se entera).
3. Arrancar el agente como servicio de usuario (`remote_agent.service`) en vez de la tarea programada de Windows.
4. La voz: el mismo `jarvis_voz.py` con PipeWire; el modelo de "Hey Jarvis" (sherpa) funciona en Linux.
5. `exportar_nombres.ps1` → versión `.sh` que lea `/usr/share/applications/*.desktop`, Steam
   (`~/.local/share/Steam/steamapps/appmanifest_*.acf`) y Heroic (`~/.config/heroic/`).

**Factibilidad:** el cerebro, Hermes y Telegram, al 100 % hoy. El PC en Omarchy: factible, aproximadamente un fin de
semana de trabajo para reescribir las acciones del agente (son unas 40, la mayoría de una línea con `grim`/`wtype`/`hyprctl`).
Lo más delicado: las coordenadas con dos pantallas con escalas distintas en Hyprland (se leen con `hyprctl monitors -j`).
