#!/usr/bin/env bash
# JARVIS: arreglo del 24/10 para el PC Linux, aplicado EN VIVO en el portátil (lo que de verdad corre).
# Problema: el cerebro decidía «PC encendido» probando puertos del PC Windows (8765/11434) y un ping con
# opciones de Windows; en el PC Linux eso falla SIEMPRE -> «el PC ya está apagado» y no se mandaba nada.
# Ahora: encendido = el agente del PC está conectado al hub (18765), y si no, ping de Linux o SSH (22).
# Uso (en el portátil):  bash ~/jarvis-repo/tools/arreglo-pc-linux.sh
# Deja copia de seguridad, comprueba sintaxis, reinicia hermes-gateway y enseña el estado.
set -euo pipefail
S=~/jarvis2/scripts; P=~/jarvis-control/plugin-silencio/index.js
B=~/jarvis-backups/arreglo-pc-linux-$(date +%Y%m%d-%H%M%S); mkdir -p "$B"
for f in "$S/pc_do.py" "$S/pc_power.py" "$S/estado.py" "$S/wake_pc.py" "$P"; do [ -f "$f" ] && cp -a "$f" "$B/"; done
echo "Copia de seguridad en $B"
python3 - "$S" "$P" <<'EOF'
import os, re, sys, tomllib
S, P = sys.argv[1], sys.argv[2]
pc_ip = tomllib.load(open(os.path.expanduser("~/.config/jarvis/config.toml"), "rb"))["pc_ip"]
WIN_PING = '["ping", "-n", "1", "-w", "1000", ip]'
LIN_PING = '(["ping", "-n", "1", "-w", "1000", ip] if os.name == "nt" else ["ping", "-c", "1", "-W", "1", ip])'

def patch(path, pares, add_os=False):
    if not os.path.exists(path):
        print("  (no existe)", path); return
    s = o = open(path, encoding="utf-8").read()
    if add_os and not re.search(r"^import os\b", s, re.M):
        s = re.sub(r"^import json\n", "import json\nimport os\n", s, count=1, flags=re.M)
    for a, b in pares:
        if b in s:
            continue
        if a not in s:
            print("  AVISO: no encuentro el trozo a cambiar en", path, "->", a[:60]); continue
        s = s.replace(a, b)
    if s != o:
        open(path, "w", encoding="utf-8").write(s); print("  cambiado", path)
    else:
        print("  ya estaba", path)

patch(f"{S}/pc_do.py", [(WIN_PING, LIN_PING), (
'''def pc_awake() -> bool:
    return (_ping_ok(PC_IP) or _tcp_ok(PC_IP, 18765, 2)
            or _tcp_ok(PC_IP, 11434, 2))''',
'''def pc_awake() -> bool:
    # el PC Linux no expone 18765/11434 a la red: vale el agente conectado, el ping o su SSH
    return (_agente_conectado() or _ping_ok(PC_IP) or _tcp_ok(PC_IP, 22, 2)
            or _tcp_ok(PC_IP, 18765, 2) or _tcp_ok(PC_IP, 11434, 2))''')])
patch(f"{S}/pc_power.py", [(WIN_PING, LIN_PING)])
patch(f"{S}/estado.py", [(WIN_PING, LIN_PING), (
"pc_up = ping_ok(PC_IP) or tcp_ok(PC_IP, 11434) or tcp_ok(PC_IP, 8765)",
"pc_up = ping_ok(PC_IP) or tcp_ok(PC_IP, 22) or tcp_ok(PC_IP, 11434) or tcp_ok(PC_IP, 8765)")], add_os=True)
patch(f"{S}/wake_pc.py", [
('["ping", "-n", "1", "-w", str(PING_TIMEOUT_MS), ip]',
 '(["ping", "-n", "1", "-w", str(PING_TIMEOUT_MS), ip] if os.name == "nt"\n             else ["ping", "-c", "1", "-W", str(max(1, PING_TIMEOUT_MS // 1000)), ip])'),
("TCP_PORTS = (11434, 8765)", "TCP_PORTS = (22, 11434, 8765)  # 22 = SSH del PC Linux")])
patch(P, [
('const JX_ASLEEP = "El PC está apagado, señor. Dígame «enciende el PC» y lo despierto.";',
 'const JX_ASLEEP = "No llego al PC, señor: está apagado o su agente no está conectado. No he ejecutado nada. Dígame «enciende el PC» y lo despierto.";'),
('''function _jxAwake(timeoutMs = 1500) {
  const tryPort = (port) => new Promise((res) => {''',
'''function _jxAgente() {
  // el agente del PC (Linux) se conecta al hub del portátil (puerto 18765): eso es «encendido y listo»
  return new Promise((res) => {
    _jxExecFile("ss", ["-tnH", "state", "established", "( sport = :18765 )"], { timeout: 5000 }, (err, stdout) => {
      res(!err && String(stdout || "").includes("%s:"));
    });
  });
}

async function _jxAwake(timeoutMs = 1500) {
  if (await _jxAgente()) return true;
  const tryPort = (port) => new Promise((res) => {''' % pc_ip),
('''  return Promise.all([tryPort(8765), tryPort(11434)]).then((r) => r.some(Boolean));
}''',
'''  // 22 = SSH del PC Linux; 8765/11434 quedan por el PC Windows
  return Promise.all([tryPort(22), tryPort(8765), tryPort(11434)]).then((r) => r.some(Boolean));
}
const JX_SIN_AGENTE = "No llego al PC, señor: su agente no está conectado al cerebro. Puede estar apagado o fuera de la red de casa; no he ejecutado nada.";'''),
('if (!awake) return r.act === "shutdown" ? "El PC ya está apagado, señor." : JX_ASLEEP;',
 'if (!awake) return r.act === "shutdown" ? JX_SIN_AGENTE : JX_ASLEEP;')])
EOF
for f in pc_do.py pc_power.py estado.py wake_pc.py; do python3 -m py_compile "$S/$f"; done
node --check "$P"
echo "Sintaxis bien. Reinicio el gateway de Hermes para que cargue el plugin nuevo..."
systemctl --user restart hermes-gateway.service; sleep 3; systemctl --user is-active hermes-gateway.service
echo "Agente del PC conectado al hub:"; ss -tnH state established '( sport = :18765 )' || true
python3 "$S/pc_do.py" status || true
