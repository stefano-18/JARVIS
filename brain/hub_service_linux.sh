#!/bin/bash
# hub 18765 en LAN (0.0.0.0) — el hub.py bindea segun JR_HOST/JR_PORT
set -e
cd {{HOME}}/jarvis2
export JR_HOST="0.0.0.0"
export JR_PORT="18765"
exec {{HOME}}/jarvis2/.venv/bin/python scripts/hub_service.py
