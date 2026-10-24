#!/usr/bin/env bash
# JARVIS: instala en un PC con Linux (Omarchy/Arch + Hyprland) el agente y la voz que el cerebro del portátil controla.
# Uso:  bash pc-windows/linux/instalar-pc-linux.sh <IP-del-portátil> [--simulacion]
# El secreto del hub (el mismo JARVIS_REMOTE_SECRET del portátil) se pide por teclado y no se muestra.
set -euo pipefail
IP="${1:-}"; SIM=0; [ "${2:-}" = "--simulacion" ] && SIM=1
[ -n "$IP" ] || { echo "uso: $0 <IP-del-portátil> [--simulacion]"; exit 2; }
R="$(cd "$(dirname "$0")/../.." && pwd)"; V=~/.local/share/jarvis/venv-voz; C=~/.config/jarvis-pc; U=~/.config/systemd/user
haz() { echo "+ $*"; [ $SIM = 1 ] || bash -c "$*"; }
[ "$R" = "$HOME/jarvis-repo" ] || echo "Aviso: los servicios esperan el repositorio en ~/jarvis-repo (está en $R)."

haz "sudo pacman -S --needed --noconfirm python grim slurp wtype ydotool wl-clipboard playerctl portaudio jq"
haz "systemctl --user enable --now ydotool.service || true"
haz "python3 -m venv '$V' && '$V/bin/pip' install -q websockets psutil requests numpy edge-tts sherpa-onnx openwakeword pyaudio"

if [ $SIM = 0 ] && [ ! -f "$C/agent.env" ]; then
  read -rsp "Secreto del hub (JARVIS_REMOTE_SECRET del portátil): " S; echo
  mkdir -p "$C"; umask 077
  printf 'DEVICE_ID=pc-01\nSECRET=%s\nHUB_HOST=%s\nHUB_PORT=18765\nSCREEN_C1=1\nMEDIA_VOLUME=1\nROOTS=%s\nYDOTOOL_SOCKET=/tmp/.ydotool_socket\n' \
    "$S" "$IP" "$HOME" > "$C/agent.env"
  echo "Guardado $C/agent.env (permisos 600)."
fi

haz "mkdir -p '$U' && cp '$R/services/pc-linux/jarvis-agente.service' '$U/'"
haz "sed 's/{{PORTATIL_IP}}/$IP/' '$R/services/pc-linux/jarvis-voz.service' > '$U/jarvis-voz.service'"
haz "systemctl --user daemon-reload && systemctl --user enable --now jarvis-agente.service jarvis-voz.service"
[ $SIM = 1 ] && exit 0
sleep 8
if grep -q "Conectado y autenticado" <(tail -5 "$R/pc-windows/remote_agent/logs/remote_agent.log" 2>/dev/null); then
  echo "Listo: el agente está conectado al cerebro ($IP:18765)."
else
  echo "El agente aún no conecta con $IP:18765. Mira: tail -f $R/pc-windows/remote_agent/logs/remote_agent.log"
fi
