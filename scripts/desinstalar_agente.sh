#!/usr/bin/env bash
# =============================================================================
#  SDMR - Desinstalador del Agente (Linux)
# =============================================================================
#  Detiene el agente que este corriendo, quita el archivo de autostart
#  (~/.config/autostart/sdmr-agent.desktop) y elimina la regla ufw del canal
#  de comandos si se creo desde el instalador.
#  No borra el codigo del proyecto ni agent/config.ini.
# =============================================================================
set -euo pipefail

# Raiz del proyecto (resolviendo symlinks, igual que el instalador)
SRC="${BASH_SOURCE[0]}"
while [ -L "$SRC" ]; do
    DIR="$(cd -P "$(dirname "$SRC")" && pwd)"
    SRC="$(readlink "$SRC")"
    [[ "$SRC" != /* ]] && SRC="$DIR/$SRC"
done
RAIZ="$(cd -P "$(dirname "$SRC")/.." && pwd)"

AUTOSTART_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/autostart"
DESKTOP="$AUTOSTART_DIR/sdmr-agent.desktop"

echo "==================================================================="
echo " SDMR - Desinstalacion del Agente"
echo "==================================================================="

# --------------------------- Detener el agente ------------------------------
# Se busca por el nombre del script, no por usuario: mata solo procesos SDMR.
# pgrep puede faltar en sistemas minimos; se usa ps+grep como alternativa.
if command -v pgrep >/dev/null 2>&1; then
    PIDS="$(pgrep -f 'agent.py --silent' || true)"
else
    PIDS="$(ps -eo pid=,args= 2>/dev/null | grep '[a]gent.py --silent' | awk '{print $1}' || true)"
fi
if [ -n "$PIDS" ]; then
    echo "$PIDS" | xargs -r kill 2>/dev/null || true
    echo "Agente detenido (PIDs: $PIDS)."
else
    echo "No hay agentes corriendo en este equipo."
fi

# --------------------------- Archivo de autostart ---------------------------
if [ -f "$DESKTOP" ]; then
    rm -f "$DESKTOP"
    echo "Archivo de autostart eliminado: $DESKTOP"
else
    echo "No habia archivo de autostart en $AUTOSTART_DIR."
fi

# ------------------------------- Regla ufw ----------------------------------
if command -v ufw >/dev/null 2>&1; then
    if [ "$(id -u)" -eq 0 ]; then
        PUERTO_CMD="$(sed -n 's/^puerto_cmd *= *//p' "$RAIZ/agent/config.ini" 2>/dev/null | head -n1)"
        PUERTO_CMD="${PUERTO_CMD:-5002}"
        if ufw status 2>/dev/null | grep -q "$PUERTO_CMD/tcp.*ALLOW"; then
            ufw delete allow "$PUERTO_CMD/tcp" >/dev/null
            echo "Regla ufw '$PUERTO_CMD/tcp' eliminada."
        else
            echo "No habia regla ufw para TCP $PUERTO_CMD."
        fi
    else
        echo "Sin derechos root: no se toca el firewall."
        echo "Para quitarla a mano: sudo ufw status numbered"
    fi
fi

echo
echo "Listo. El agente no arrancara mas al iniciar sesion."
echo "Para volver a instalarlo: ./instalar_agente.sh"
