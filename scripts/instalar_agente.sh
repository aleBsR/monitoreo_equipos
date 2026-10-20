#!/usr/bin/env bash
# =============================================================================
#  SDMR - Instalador del Agente en este equipo (Linux)
# =============================================================================
#  Deja el Agente de Monitoreo corriendo SIN TERMINAL, oculto, cada vez que
#  el usuario inicia sesión (autostart XDG). El equipo aparece solo en el
#  dashboard del administrador.
#
#  Uso:
#      ./instalar_agente.sh [IP_SERVIDOR] [ID_NODO] [PUERTO_UDP] [PUERTO_CMD]
#      ./instalar_agente.sh --desinstalar
#
#  Ejemplos:
#      ./instalar_agente.sh                      # IP via broadcast (automatico)
#      ./instalar_agente.sh 192.168.1.50         # IP fija escrita en config.ini
#      ./instalar_agente.sh 192.168.1.50 LAPTOP-JUAN
#
#  Que hace:
#    1. Verifica Python 3.
#    2. Escribe agent/config.ini (si se pasa la IP o si aun no existe).
#    3. Crea ~/.config/autostart/sdmr-agent.desktop (arranque oculto al login).
#    4. Abre la regla ufw del canal de comandos (si ufw esta instalado).
#    5. Arranca el agente AHORA mismo, sin ventana.
#
#  Para quitarlo: ./desinstalar_agente.sh   (o este mismo con --desinstalar)
# =============================================================================
set -euo pipefail

# Raiz del proyecto (resolviendo symlinks, igual que agente_remoto.sh)
SRC="${BASH_SOURCE[0]}"
while [ -L "$SRC" ]; do
    DIR="$(cd -P "$(dirname "$SRC")" && pwd)"
    SRC="$(readlink "$SRC")"
    [[ "$SRC" != /* ]] && SRC="$DIR/$SRC"
done
RAIZ="$(cd -P "$(dirname "$SRC")/.." && pwd)"

AGENTE="$RAIZ/agent/agent.py"
CONFIG="$RAIZ/agent/config.ini"
AUTOSTART_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/autostart"
DESKTOP="$AUTOSTART_DIR/sdmr-agent.desktop"

if [ "${1:-}" = "--desinstalar" ]; then
    exec "$RAIZ/scripts/desinstalar_agente.sh"
fi

echo "==================================================================="
echo " SDMR - Instalacion del Agente (arranque automatico)"
echo "==================================================================="

# ------------------------------ Interprete ---------------------------------
PY="${PYTHON:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
    echo
    echo "ERROR: no se encontro '$PY'. Instala Python 3.8 o superior:"
    echo "    sudo apt install python3        # Debian / Ubuntu"
    echo "    sudo dnf install python3        # Fedora"
    echo
    exit 1
fi

if [ ! -f "$AGENTE" ]; then
    echo "ERROR: no existe '$AGENTE'."
    echo "Este instalador debe estar dentro de la carpeta scripts/ del proyecto SDMR."
    exit 1
fi

PY_BIN="$(command -v "$PY")"

# ---------------------------- agent/config.ini ------------------------------
IP_SERVIDOR="${1:-}"
ID_NODO="${2:-}"
PUERTO_UDP="${3:-5000}"
PUERTO_CMD="${4:-5002}"

escribir_config() {
    cat > "$CONFIG" <<EOF
[nodo]
id_nodo=$ID_NODO

[red]
ip_servidor=$IP_SERVIDOR
puerto_udp=$PUERTO_UDP
puerto_cmd=$PUERTO_CMD
intervalo=3
EOF
}

if [ -n "$IP_SERVIDOR" ]; then
    escribir_config
    echo "[2/5] config.ini escrito con ip_servidor=$IP_SERVIDOR"
elif [ -f "$CONFIG" ]; then
    echo "[2/5] Se conserva el config.ini existente: $CONFIG"
else
    escribir_config
    echo "[2/5] config.ini creado SIN ip_servidor: el agente descubrira al"
    echo "      Servidor Central solo, por broadcast (SRVREQ -> SRVINFO)."
fi

# -------------------- Archivo .desktop de autostart -------------------------
# ~/.config/autostart no requiere root y arranca el agente apenas el usuario
# inicia sesión, sin ventana de terminal.
mkdir -p "$AUTOSTART_DIR"
cat > "$DESKTOP" <<EOF
[Desktop Entry]
Type=Application
Version=1.0
Name=SDMR - Agente de monitoreo
Comment=Agente oculto que envia telemetria al Servidor Central SDMR
Exec=sh -c "exec '$PY_BIN' '$AGENTE' --silent"
Icon=utilities-system-monitor
Terminal=false
X-GNOME-Autostart-enabled=true
X-GNOME-Autostart-Delay=5
EOF
echo "[3/5] Archivo de autostart creado:"
echo "      $DESKTOP"

# ---------------------------- Regla ufw -------------------------------------
# Solo hace falta para el EXEC remoto; la telemetria UDP saliente funciona
# aunque el firewall del cliente este activo.
if command -v ufw >/dev/null 2>&1; then
    if [ "$(id -u)" -eq 0 ]; then
        if ufw status 2>/dev/null | grep -q "$PUERTO_CMD/tcp.*ALLOW"; then
            echo "[4/5] La regla ufw para TCP $PUERTO_CMD ya existe: se deja como esta."
        else
            ufw allow "$PUERTO_CMD/tcp" >/dev/null
            echo "[4/5] Regla ufw agregada para el canal EXEC (TCP $PUERTO_CMD)."
        fi
    else
        echo "[4/5] Sin derechos root: se omite la regla ufw."
        echo "      La telemetria llegara igual; solo el EXEC remoto podria fallar."
        echo "      Para agregarla: sudo ufw allow $PUERTO_CMD/tcp"
    fi
else
    echo "[4/5] No hay ufw instalado: no se toca el firewall."
fi

# -------------------------- Arranque inmediato ------------------------------
# El agente escribe su propio log en agent/agente.log; la salida de la terminal
# se descarta porque el proceso queda en segundo plano.
nohup "$PY_BIN" "$AGENTE" --silent >/dev/null 2>&1 &
AGENTE_PID=$!
sleep 1
if kill -0 "$AGENTE_PID" 2>/dev/null; then
    echo "[5/5] Agente arrancado en segundo plano (PID $AGENTE_PID)."
else
    echo "[5/5] AVISO: el agente no arranco. Mirá agent/agente.log."
fi

echo
echo "==================================================================="
echo " INSTALACION TERMINADA"
echo "  - Arranca solo al iniciar sesion (oculto, sin terminal)."
echo "  - Log del agente: $RAIZ/agent/agente.log"
echo "  - El equipo aparecera en la pestana 'Nodos' del dashboard."
echo
echo "  En el equipo del administrador:"
echo "      python3 client/gui_monitor.py"
echo "  y conectate al Servidor Central. Si el agente no tiene IP escrita,"
echo "  la descubre solo por broadcast."
echo "==================================================================="
