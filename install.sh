#!/usr/bin/env bash
# JARVIS: instalador del cerebro para Linux (Ubuntu/Lubuntu con apt, o Arch/Omarchy con pacman).
# Uso: ./install.sh [--dry-run]
#  1. si no hay ~/.config/jarvis/config.toml, lanza setup.py (pregunta datos y claves en este equipo)
#  2. instala dependencias, crea ~/jarvis2/.venv
#  3. copia brain/, hermes/ y services/ poniendo los datos de este equipo en los marcadores {{...}}
set -euo pipefail
DRY=0; [ "${1:-}" = "--dry-run" ] && DRY=1
R="$(cd "$(dirname "$0")" && pwd)"
J="$HOME/jarvis2"; S="$J/scripts"; CFG="$HOME/.config/jarvis"; U="$HOME/.config/systemd/user"
haz() { if [ $DRY = 1 ]; then echo "[simulación] $*"; else echo "+ $*"; eval "$@"; fi; }

if command -v pacman >/dev/null; then
  SIS="arch"; INSTALA="sudo pacman -S --needed --noconfirm python python-pip nodejs npm git rsync openssh iputils gzip patch ffmpeg"
elif command -v apt-get >/dev/null; then
  SIS="debian"; INSTALA="sudo apt-get update && sudo apt-get install -y python3 python3-venv python3-pip nodejs npm git rsync openssh-client iputils-ping gzip patch ffmpeg"
else
  echo "No reconozco el gestor de paquetes (ni apt ni pacman)."; exit 1
fi
echo "== Sistema: $SIS ($( [ $DRY = 1 ] && echo simulación || echo de verdad ))"

if [ ! -f "$CFG/config.toml" ]; then
  echo "== Primera vez: datos y claves de este equipo"
  haz "python3 '$R/setup.py'"
fi
haz "$INSTALA"

echo "== Copia con los datos de este equipo"
T="$(mktemp -d)"
haz "cp -r '$R/brain' '$R/hermes' '$R/services' '$T/'"
haz "python3 '$R/tools/rellenar.py' '$T'"

echo "== Cerebro y entorno de Python"
haz "mkdir -p '$S' '$CFG' '$U' '$HOME/tareas/auditoria' '$HOME/jarvis-equipo' '$HOME/backups'"
haz "rsync -a '$T/brain/' '$S/'"
haz "python3 -m venv '$J/.venv'"
haz "'$J/.venv/bin/pip' install -q -r '$R/requirements.txt'"
haz "'$J/.venv/bin/pip' install -q websockets pillow numpy faster-whisper edge-tts"
haz "python3 -m venv '$HOME/jarvis-control/gvenv' && '$HOME/jarvis-control/gvenv/bin/pip' install -q google-api-python-client google-auth-oauthlib"

echo "== Hermes (plugins, filtro, skills y personalidad)"
haz "mkdir -p '$HOME/.hermes/plugins' '$HOME/.hermes/skills' '$HOME/jarvis-control/plugin-silencio'"
haz "rsync -a '$T/hermes/plugins/' '$HOME/.hermes/plugins/'"
haz "rsync -a '$T/hermes/plugin-silencio/' '$HOME/jarvis-control/plugin-silencio/'"
haz "rsync -a '$T/hermes/skills/' '$HOME/.hermes/skills/'"
[ -f "$HOME/.hermes/SOUL.md" ] || haz "cp '$T/hermes/SOUL.md' '$HOME/.hermes/SOUL.md'"
haz "chmod 700 '$CFG' '$HOME/jarvis-control' '$HOME/.hermes'"

echo "== Servicios de usuario"
haz "cp '$T'/services/usuario/jarvis-*.service '$T'/services/usuario/jarvis-*.timer '$U/'"
haz "systemctl --user daemon-reload"
haz "systemctl --user enable --now jarvis-agenda.service jarvis-vigilante.timer jarvis-pron.timer"
echo "   El servidor de voz (jarvis-v2) es de sistema: sudo cp $T/services/sistema/jarvis-v2.service /etc/systemd/system/ (ver docs/)"
haz "rm -rf '$T'"

cat <<'FIN'

== Falta a mano:
  1. La palabra clave: ~/jarvis2/.venv/bin/python ~/jarvis2/scripts/jarvis_gate.py (nunca por chat).
  2. Google (opcional): ~/jarvis-control/gvenv/bin/python ~/jarvis2/scripts/google_jx.py auth
  3. Instalar Hermes con su instalador oficial y comprobar: ~/jarvis2/.venv/bin/python ~/jarvis2/scripts/jx_autotest.py
  4. El PC con Windows: pc-windows/instalar-pc.ps1 (ver README).
FIN
