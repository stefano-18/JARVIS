#!/usr/bin/env bash
# Busca claves en los archivos que se le pasen (o en todos los del repo) y en el historial si se pide --historial.
# Nunca muestra el valor: solo archivo:línea y el tipo. Sale con 1 si encuentra algo.
cd "$(git rev-parse --show-toplevel)" || exit 2
declare -A TIPOS=(
  [anthropic]='sk-ant-[A-Za-z0-9_-]{10,}'
  [openai]='sk-(proj-)?[A-Za-z0-9_-]{32,}'
  [groq]='gsk_[A-Za-z0-9]{20,}'
  [google_api]='AIza[0-9A-Za-z_-]{30,}'
  [google_oauth]='ya29\.[0-9A-Za-z_-]{20,}|GOCSPX-[0-9A-Za-z_-]{10,}|1//0[0-9A-Za-z_-]{30,}'
  [telegram_bot]='[0-9]{8,10}:[A-Za-z0-9_-]{35}'
  [github]='ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|gho_[A-Za-z0-9]{30,}'
  [openrouter]='sk-or-v1-[A-Za-z0-9]{20,}'
  [slack]='xox[abprs]-[A-Za-z0-9-]{10,}'
  [clave_privada]='-----BEGIN [A-Z ]*PRIVATE KEY-----'
  [password]='(password|passwd|contrase(ñ|n)a|secret)[\"'"'"' ]*[:=][ ]*[\"'"'"'][^\"'"'"' {}<$]{8,}[\"'"'"']'
)
# lo que no es una clave: este propio archivo, valores de prueba y ejemplos
EXCL='SECRET = "tests|ejemplo|example|pon-aqui|placeholder'
if [ "$1" = "--historial" ]; then
  malos=0
  for t in "${!TIPOS[@]}"; do
    n=$(git log -p --all -- . ':!tools/escanear_claves.sh' | grep -E "^\+" | grep -iE -e "${TIPOS[$t]}" | grep -viE "$EXCL" | wc -l)
    [ "$n" -gt 0 ] && { echo "historial: $n línea(s) tipo $t"; malos=1; }
  done
  exit $malos
fi
if [ $# -gt 0 ]; then ARCH=("$@"); else mapfile -t ARCH < <(git ls-files); fi
malos=0
for f in "${ARCH[@]}"; do
  [ -f "$f" ] || continue
  case "$f" in tools/escanear_claves.sh) continue;; esac
  for t in "${!TIPOS[@]}"; do
    grep -nIiE -e "${TIPOS[$t]}" "$f" 2>/dev/null | grep -viE "$EXCL" | cut -d: -f1 | while read -r l; do echo "$f:$l [$t]"; done | grep . && malos=1
  done
done
for f in "${ARCH[@]}"; do
  case "$f" in *.env|.env|.env.*|*.key|*clave.hash|*google-token*.json|*credentials*.json) [[ "$f" == *example* ]] || { echo "$f [archivo de claves]"; malos=1; };; esac
done
exit $malos
