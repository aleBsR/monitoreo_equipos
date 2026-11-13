#!/usr/bin/env bash
# =============================================================================
#  SDMR - Centro de Control (Linux)
# =============================================================================
#  Arranca el panel local de control y lo abre en el navegador. Desde el panel
#  se prende/apaga todo el stack (servidor, gateway, web, escaneo, agentes) sin
#  tocar la terminal.
#
#  Uso:
#      ./centro_control.sh            # panel en http://127.0.0.1:7070
#      ./centro_control.sh 7075       # otro puerto
# =============================================================================
set -euo pipefail

# Resolver la raíz aun si el script se invoca por symlink (igual que 'sdmr').
SRC="${BASH_SOURCE[0]}"
while [ -L "$SRC" ]; do
    DIR="$(cd -P "$(dirname "$SRC")" && pwd)"
    SRC="$(readlink "$SRC")"
    [[ "$SRC" != /* ]] && SRC="$DIR/$SRC"
done
RAIZ="$(cd -P "$(dirname "$SRC")/.." && pwd)"

PY="${PYTHON:-python3}"
PUERTO="${1:-7070}"
URL="http://127.0.0.1:${PUERTO}"

if ! command -v "$PY" >/dev/null 2>&1; then
    echo "ERROR: no se encontró '$PY'. Instalá Python 3.8 o superior."
    exit 1
fi

# Abrir el navegador un segundo después (cuando el panel ya escucha).
( sleep 1; command -v xdg-open >/dev/null 2>&1 && xdg-open "$URL" >/dev/null 2>&1 || true ) &

echo "SDMR Centro de Control -> $URL  (Ctrl+C para cerrar)"
exec "$PY" "$RAIZ/scripts/centro_control.py" "$PUERTO"
