#!/usr/bin/env bash
# Publica la app completa desde este computador con un túnel gratuito de Cloudflare.
# Uso: bash scripts/publicar_tunel.sh [--sin-clave]   (Ctrl+C para cerrarla; la URL cambia cada vez)
# Pide RADAR_PASSWORD del .env salvo con --sin-clave (abierta a cualquiera con el enlace, p. ej. jurados).
# Si la app se cae, se vuelve a abrir sola en el mismo puerto: la URL no cambia.
# La URL queda en out/url-publica.txt y el enlace fijo https://caroujueta.github.io/creativIA/ redirige a ella
# (necesita gh con sesión iniciada). Requiere cloudflared en el PATH (o en ~/.local/bin).
set -euo pipefail
cd "$(dirname "$0")/.."
PUBLIC=--public
if [ "${1:-}" = "--sin-clave" ]; then
  PUBLIC=""
else
  grep -q '^RADAR_PASSWORD=.\+' .env || { echo "Falta RADAR_PASSWORD en el .env (o usa --sin-clave)"; exit 1; }
fi
CF=$(command -v cloudflared || echo "$HOME/.local/bin/cloudflared")
REPO=CaroUjueta/creativIA
FIXED=https://caroujueta.github.io/creativIA/

# El enlace fijo (GitHub Pages, rama gh-pages) lee url.txt y redirige al túnel del día.
update_fixed_link() {
  local sha
  sha=$(gh api "repos/$REPO/contents/url.txt?ref=gh-pages" --jq .sha 2>/dev/null) || sha=""
  if gh api -X PUT "repos/$REPO/contents/url.txt" -f message="Túnel del día" -f branch=gh-pages \
       -f content="$(printf '%s\n' "$1" | base64 -w0)" ${sha:+-f sha="$sha"} > /dev/null 2>&1; then
    echo "Enlace fijo para compartir: $FIXED  (redirige a esta URL en 1–2 minutos)"
  else
    echo "No se pudo actualizar el enlace fijo (¿gh auth login?). Comparte la URL de arriba."
  fi
}
PORT=${PORT:-8000}
mkdir -p out

(while true; do
  .venv/bin/python -m radar.web $PUBLIC --no-open --port "$PORT" >> out/app.log 2>&1 || true
  echo "$(date '+%H:%M') La app se detuvo; reabriéndola…" | tee -a out/app.log
  sleep 3
done) &
APP=$!
trap 'kill $APP 2>/dev/null; pkill -f "radar.web .*--port $PORT" 2>/dev/null' EXIT
sleep 2
echo "Abriendo el túnel… la URL pública es la que termina en .trycloudflare.com"
"$CF" tunnel --no-autoupdate --url "http://127.0.0.1:$PORT" 2>&1 \
  | grep --line-buffered -oE 'https://[a-z0-9-]+\.trycloudflare\.com' \
  | while read -r url; do
      echo "$url" > out/url-publica.txt
      echo "App en línea: $url"
      update_fixed_link "$url"
    done
