#!/usr/bin/env bash
# Crea accesos directos en el Escritorio para abrir la mini interfaz (Linux).
set -euo pipefail
SRC="${BASH_SOURCE[0]}"
while [ -L "$SRC" ]; do
    DIR="$(cd -P "$(dirname "$SRC")" && pwd)"
    SRC="$(readlink "$SRC")"
    [[ "$SRC" != /* ]] && SRC="$DIR/$SRC"
done
RAIZ="$(cd -P "$(dirname "$SRC")/../.." && pwd)"
DESKTOP="${XDG_DESKTOP_DIR:-$HOME/Escritorio}"
[ -d "$DESKTOP" ] || DESKTOP="$HOME/Desktop"
mkdir -p "$DESKTOP"
cat > "$DESKTOP/SDMR-Control-Agente.desktop" <<EOF
[Desktop Entry]
Type=Application
Version=1.0
Name=SDMR Control Agente
Comment=Mini interfaz para iniciar/detener el agente SDMR
Exec=$RAIZ/scripts/agent/lanzar_gui.sh
Icon=utilities-system-monitor
Terminal=false
Categories=Utility;
EOF
chmod +x "$DESKTOP/SDMR-Control-Agente.desktop"
echo "Acceso directo creado en: $DESKTOP/SDMR-Control-Agente.desktop"
