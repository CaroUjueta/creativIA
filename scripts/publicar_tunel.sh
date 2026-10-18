#!/usr/bin/env bash
# Publica la app completa desde este computador con un túnel gratuito de Cloudflare.
# Uso: bash scripts/publicar_tunel.sh [--sin-clave]   (Ctrl+C para cerrarla; la URL cambia cada vez)
# Pide RADAR_PASSWORD del .env salvo con --sin-clave (abierta a cualquiera con el enlace, p. ej. jurados).
# Requiere cloudflared en el PATH (o en ~/.local/bin).
set -euo pipefail
cd "$(dirname "$0")/.."
PUBLIC=--public
if [ "${1:-}" = "--sin-clave" ]; then
  PUBLIC=""
else
  grep -q '^RADAR_PASSWORD=.\+' .env || { echo "Falta RADAR_PASSWORD en el .env (o usa --sin-clave)"; exit 1; }
fi
CF=$(command -v cloudflared || echo "$HOME/.local/bin/cloudflared")
PORT=${PORT:-8000}

.venv/bin/python -m radar.web $PUBLIC --no-open --port "$PORT" &
APP=$!
trap 'kill $APP 2>/dev/null' EXIT
sleep 2
echo "Abriendo el túnel… la URL pública es la que termina en .trycloudflare.com"
"$CF" tunnel --no-autoupdate --url "http://127.0.0.1:$PORT" 2>&1 | grep --line-buffered -oE 'https://[a-z0-9-]+\.trycloudflare\.com' | sed -u 's/^/App en línea: /'
