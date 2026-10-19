#!/usr/bin/env bash
# JARVIS: actualiza ~/jarvis-repo con lo que funciona ahora en el portátil y lo sube a GitHub.
# Luego en el PC (PowerShell): cd "$HOME\Desktop\JARVIS 2.0"; git pull jarvis:jarvis-repo main   y en GitHub Desktop: Push origin
# Luego en el PC: cd "C:SERS<USUARIO>DESKTOPJARVIS 2.0"; GIT PULL JARVIS:JARVIS-REPO MAIN   Y EN GITHUB DESKTOP: PUSH ORIGIN
# Copia brain/hermes/servicios, quita datos personales (marcadores), busca claves y SOLO si está limpio hace commit y push.
set -e
R=~/jarvis-repo; MSG="${1:-Actualización de JARVIS}"
EXC=(--exclude='*.bak*' --exclude=__pycache__ --exclude='.env*' --exclude='*.key' --exclude='*token*' --exclude='*secret*' --exclude='*.log' --exclude='*.pyc')
rsync -a "${EXC[@]}" --exclude=install_playwright.py --exclude=ollama_bench.py --exclude=restaurar_energia.ps1 --exclude=sim_brain_requests.py \
  --exclude=smoke_remote.py --exclude=start_watchdog.bat --exclude=telegram_estado.ps1 ~/jarvis2/scripts/ $R/brain/
cp ~/.hermes/SOUL.md $R/hermes/; rsync -a "${EXC[@]}" ~/.hermes/plugins/ $R/hermes/plugins/
rsync -a "${EXC[@]}" --exclude=node_modules ~/jarvis-control/plugin-silencio/ $R/hermes/plugin-silencio/
cp ~/.config/systemd/user/jarvis-*.service ~/.config/systemd/user/jarvis-*.timer $R/services/usuario/ 2>/dev/null || true
python3 $R/tools/anonimizar.py $R
PAT='sk-ant-[A-Za-z0-9_-]{10,}|gsk_[A-Za-z0-9]{20,}|[0-9]{8,10}:AA[A-Za-z0-9_-]{30,}|AIza[0-9A-Za-z_-]{30,}|sk-or-v1-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{30,}|-----BEGIN [A-Z ]*PRIVATE KEY-----'
cd $R
if git ls-files -o -c --exclude-standard -z | xargs -0 grep -lIE "$PAT" 2>/dev/null; then echo "PARO: hay algo que parece una clave (arriba). No subo nada."; exit 1; fi
python3 tests/test_basico.py | tail -1
git add -A
if git diff --cached --quiet; then echo "No hay cambios que subir."; exit 0; fi
git commit -q -m "$MSG" && echo "commit: $(git log --oneline | head -1)"
if git remote | grep -q origin; then git push && echo "Subido a GitHub."; else echo "Aún no hay remoto (ver docs/GITHUB.md)."; fi
