#!/usr/bin/env bash
# =============================================================================
#  SDMR - Instalador para Debian/Ubuntu (y derivados)
# =============================================================================
#  Deja el sistema listo para abrir todo con un solo comando:
#
#      1. Verifica Python 3.8+.
#      2. Instala 'psutil' (opcional, métricas reales) si falta.
#      3. Instala 'python3-tk' si falta (necesita sudo).
#      4. Crea el comando global 'sdmr' en /usr/local/bin.
#      5. Instala el acceso de menú (.desktop) si se pide.
#
#  Uso:
#      ./instalar.sh              # instala comando 'sdmr' + acceso de menú
#      ./instalar.sh --sin-menu   # solo el comando global
#      ./instalar.sh --desinstalar
# =============================================================================
set -euo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LANZADOR="$RAIZ/scripts/sdmr"
DESTINO="/usr/local/bin/sdmr"
DESKTOP_DIR="$HOME/.local/share/applications"
DESKTOP="$DESKTOP_DIR/sdmr.desktop"

info()  { echo "[instalar] $*"; }
error() { echo "[ERROR] $*" >&2; }

desinstalar() {
    info "Quitando el comando '$DESTINO'..."
    sudo rm -f "$DESTINO"
    info "Quitando el acceso de menú..."
    rm -f "$DESKTOP"
    info "Desinstalación completa."
    exit 0
}

# ------------------------------ Argumentos -----------------------------------
INSTALAR_MENU=1
for arg in "$@"; do
    case "$arg" in
        --desinstalar) desinstalar ;;
        --sin-menu)    INSTALAR_MENU=0 ;;
        -h|--help)
            echo "Uso: $0 [--sin-menu | --desinstalar]"
            exit 0 ;;
        *) error "Opción desconocida: $arg"; exit 1 ;;
    esac
done

# ------------------------------ Python ---------------------------------------
PY="${PYTHON:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
    error "No se encontró '$PY'. Instalá Python 3.8 o superior."
    exit 1
fi
info "Python detectado: $("$PY" --version 2>&1)"

# ------------------------------ psutil (opcional) ----------------------------
if "$PY" -c "import psutil" >/dev/null 2>&1; then
    info "psutil ya está instalado (métricas reales habilitadas)."
else
    info "Instalando psutil (opcional, para métricas reales)..."
    "$PY" -m pip install --user -q "psutil>=5.9.0" || \
        info "No se pudo instalar psutil (se usarán métricas simuladas)."
fi

# ------------------------------ tkinter (interfaz) ---------------------------
if "$PY" -c "import tkinter" >/dev/null 2>&1; then
    info "tkinter ya está disponible."
else
    info "Falta tkinter: se instalará python3-tk (requiere sudo)..."
    if command -v apt-get >/dev/null 2>&1; then
        sudo apt-get update && sudo apt-get install -y python3-tk
    else
        error "No se detectó apt-get. Instalá el paquete 'python3-tk' manualmente."
        exit 1
    fi
    if ! "$PY" -c "import tkinter" >/dev/null 2>&1; then
        error "tkinter sigue sin estar disponible. Abortando."
        exit 1
    fi
    info "tkinter instalado correctamente."
fi

# ------------------------------ Comando global -------------------------------
chmod +x "$LANZADOR"
info "Creando el comando global '$DESTINO' (requiere sudo)..."
sudo ln -sf "$LANZADOR" "$DESTINO"

# ------------------------------ Acceso de menú -------------------------------
if [ "$INSTALAR_MENU" -eq 1 ]; then
    info "Instalando acceso de menú en $DESKTOP ..."
    mkdir -p "$DESKTOP_DIR"
    cat > "$DESKTOP" <<EOF
[Desktop Entry]
Type=Application
Version=1.0
Name=SDMR (Monitoreo en Red)
Comment=Sistema Distribuido de Monitoreo en Red - dashboard + servidor + agentes
Exec=$DESTINO
Terminal=false
Categories=Network;Monitor;Utility;
Icon=utilities-system-monitor
EOF
    command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$DESKTOP_DIR" || true
    info "Acceso de menú instalado."
fi

echo
info "¡Listo! Ahora podés abrir todo escribiendo:  sdmr"
