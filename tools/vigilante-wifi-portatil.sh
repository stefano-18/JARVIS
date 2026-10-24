#!/usr/bin/env bash
# JARVIS: el portátil nunca se queda sin wifi. Si la wifi se cae y NetworkManager se rinde
# (pasa tras un fallo puntual del router: «no-secrets»), cada minuto la vuelve a levantar.
# Uso (en el portátil, pide la contraseña una vez):  sudo bash ~/jarvis-repo/tools/vigilante-wifi-portatil.sh
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "Ejecútalo con sudo"; exit 1; }
cat > /usr/local/bin/jarvis-wifi-vigilante <<'EOF'
#!/usr/bin/env bash
# Si no hay ninguna conexión wifi activa, levanta la última que funcionó.
nmcli -t -f TYPE,STATE device | grep -q '^wifi:connected$' && exit 0
red=$(nmcli -t -f TIMESTAMP,NAME,TYPE connection show | sort -rn | awk -F: '$3=="802-11-wireless"{print $2; exit}')
[ -n "$red" ] || exit 0
logger -t jarvis-wifi "wifi caída: vuelvo a conectar «$red»"
nmcli radio wifi on
nmcli connection up "$red" || true
EOF
chmod 755 /usr/local/bin/jarvis-wifi-vigilante
cat > /etc/systemd/system/jarvis-wifi-vigilante.service <<'EOF'
[Unit]
Description=JARVIS: vuelve a conectar la wifi del portátil si se cae
After=NetworkManager.service

[Service]
Type=oneshot
ExecStart=/usr/local/bin/jarvis-wifi-vigilante
EOF
cat > /etc/systemd/system/jarvis-wifi-vigilante.timer <<'EOF'
[Unit]
Description=JARVIS: mirar la wifi del portátil cada minuto

[Timer]
OnBootSec=2min
OnUnitActiveSec=1min

[Install]
WantedBy=timers.target
EOF
systemctl daemon-reload
systemctl enable --now jarvis-wifi-vigilante.timer
systemctl start jarvis-wifi-vigilante.service
echo "Listo: la wifi del portátil se vuelve a conectar sola si se cae."
