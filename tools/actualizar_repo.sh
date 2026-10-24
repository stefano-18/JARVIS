#!/usr/bin/env bash
# JARVIS: actualiza ~/jarvis-repo con lo que funciona ahora en el portátil y lo sube a GitHub.
# Lo ejecuta el dueño a mano:  bash ~/jarvis-repo/tools/actualizar_repo.sh "qué ha cambiado"
# Copia brain/hermes/servicios, quita datos personales (marcadores), busca claves y SOLO si está limpio hace commit y push.
set -e
R=~/jarvis-repo; MSG="${1:-Actualización de JARVIS}"
EXC=(--exclude='*.bak*' --exclude=__pycache__ --exclude='.env*' --exclude='*.key' --exclude='*token*' --exclude='*secret*' --exclude='*.log' --exclude='*.pyc')
rsync -a "${EXC[@]}" --exclude=install_playwright.py --exclude=ollama_bench.py --exclude=restaurar_energia.ps1 --exclude=sim_brain_requests.py \
  --exclude=smoke_remote.py --exclude=start_watchdog.bat --exclude=telegram_estado.ps1 ~/jarvis2/scripts/ $R/brain/
cp ~/.hermes/SOUL.md $R/hermes/; rsync -a "${EXC[@]}" ~/.hermes/plugins/ $R/hermes/plugins/
rsync -a "${EXC[@]}" --exclude=node_modules ~/jarvis-control/plugin-silencio/ $R/hermes/plugin-silencio/
cp ~/.config/systemd/user/jarvis-*.service ~/.config/systemd/user/jarvis-*.timer $R/services/usuario/ 2>/dev/null || true
cd $R
python3 tools/anonimizar.py $R || { echo "PARO: datos personales sin anonimizar (arriba). No subo nada."; exit 1; }
git rm -q --cached --ignore-unmatch pc-windows/remote_agent/killswitch.json hermes/skills/.usage.json >/dev/null 2>&1 || true
mapfile -t TODO < <(git ls-files -o -c --exclude-standard)
bash tools/escanear_claves.sh "${TODO[@]}" || { echo "PARO: hay algo que parece una clave (arriba). No subo nada."; exit 1; }
python3 tests/test_basico.py | tail -1
git add -A
if git diff --cached --quiet; then echo "No hay cambios que subir."; exit 0; fi
git commit -q -m "$MSG" && echo "commit: $(git log --oneline | head -1)"
if git remote | grep -q origin; then git push && echo "Subido a GitHub."; else echo "Aún no hay remoto (ver docs/GITHUB.md)."; fi
