#!/usr/bin/env bash
# =============================================================================
#  SDMR - Crear acceso directo del Centro de Control (Linux)
# =============================================================================
#  Deja el icono "SDMR Centro de Control" en el menú de aplicaciones (y en el
#  Escritorio si existe). Ejecutalo UNA sola vez.
# =============================================================================
set -euo pipefail

RAIZ="$(cd -P "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LANZADOR="$RAIZ/scripts/centro_control.sh"
chmod +x "$LANZADOR" 2>/dev/null || true

APPS="$HOME/.local/share/applications"
DESKTOP="$APPS/sdmr-control.desktop"
mkdir -p "$APPS"

cat > "$DESKTOP" <<EOF
[Desktop Entry]
Type=Application
Name=SDMR Centro de Control
Comment=Encender / apagar todo el stack SDMR desde el navegador
Exec="$LANZADOR"
Icon=network-workgroup
Terminal=false
Categories=Network;
EOF
chmod +x "$DESKTOP" 2>/dev/null || true

# Copiar también al Escritorio (nombre en español o inglés), si existe.
for ESC in "$HOME/Escritorio" "$HOME/Desktop"; do
    if [ -d "$ESC" ]; then
        cp "$DESKTOP" "$ESC/sdmr-control.desktop" 2>/dev/null || true
        chmod +x "$ESC/sdmr-control.desktop" 2>/dev/null || true
    fi
done

echo "Acceso 'SDMR Centro de Control' creado en el menú de aplicaciones."
echo "Si no aparece el icono en el Escritorio, abrilo desde el menú."
