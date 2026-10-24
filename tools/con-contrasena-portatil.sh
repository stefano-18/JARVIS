#!/usr/bin/env bash
# JARVIS: lo que necesita la contraseña de administrador EN EL PORTÁTIL. Ejecútelo usted:
#   ssh jarvis        (y luego)        bash ~/jarvis-repo/tools/con-contrasena-portatil.sh
# Pide la contraseña UNA vez (sudo) y hace:
#   1) recargar los servicios (se quita el aviso "daemon-reload")
#   2) límite del registro del sistema a 300 MB
#   3) cortafuegos: voz/HUD (8765) y hub (18765) solo desde el PC; SSH solo desde la red de casa
# No borra nada. Se puede ejecutar varias veces.
set -e
PC_IP="$(python3 -c 'import tomllib,os;print(tomllib.load(open(os.path.expanduser("~/.config/jarvis/config.toml"),"rb"))["pc_ip"])')"
RED="${PC_IP%.*}.0/24"
echo "PC: $PC_IP  | red de casa: $RED"
sudo -v
echo "== 1) recargar servicios"; sudo systemctl daemon-reload
echo "== 2) límite del registro"
sudo mkdir -p /etc/systemd/journald.conf.d
printf '[Journal]\nSystemMaxUse=300M\n' | sudo tee /etc/systemd/journald.conf.d/jarvis.conf >/dev/null
sudo systemctl restart systemd-journald
echo "== 3) cortafuegos (ufw)"
command -v ufw >/dev/null || sudo apt-get install -y ufw
sudo ufw allow from "$RED" to any port 22 proto tcp comment 'SSH desde casa'
sudo ufw allow from "$PC_IP" to any port 8765 proto tcp comment 'JARVIS voz/HUD solo desde el PC'
sudo ufw allow from "$PC_IP" to any port 18765 proto tcp comment 'JARVIS hub solo desde el PC'
sudo ufw allow from "$PC_IP" to any port 8642 proto tcp comment 'Hermes API solo desde el PC'
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw --force enable
sudo ufw status numbered
echo
echo "Si arriba ve reglas antiguas que abren 8765/18765 a 'Anywhere', bórrelas con:  sudo ufw delete <número>"
echo "Listo."
