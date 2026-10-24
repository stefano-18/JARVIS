#!/bin/bash
# hub 18765: escucha en escucha_ip de config.toml (0.0.0.0 = red de casa) — el hub.py bindea segun JR_HOST/JR_PORT
set -e
cd {{HOME}}/jarvis2
export JR_HOST="$(python3 -c 'import tomllib,os;print(tomllib.load(open(os.path.expanduser("~/.config/jarvis/config.toml"),"rb")).get("escucha_ip","127.0.0.1"))' 2>/dev/null || echo 127.0.0.1)"  # arreglo 88
export JR_PORT="18765"
exec {{HOME}}/jarvis2/.venv/bin/python scripts/hub_service.py
