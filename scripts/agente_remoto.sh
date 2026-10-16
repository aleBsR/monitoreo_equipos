#!/usr/bin/env bash
# =============================================================================
#  SDMR - Lanzador de Agente Remoto (Linux)
# =============================================================================
#  Arranca un Agente de Monitoreo en ESTE equipo apuntando al Servidor Central
#  que corre en otro equipo de la red local. Pensado para la prueba del TP con
#  2 o más dispositivos (RF10: ejecutarse en al menos dos equipos en red).
#
#  Uso:
#      ./agente_remoto.sh <IP_SERVIDOR> [ID_NODO] [PUERTO_UDP] [PUERTO_CMD]
#
#  Ejemplos:
#      ./agente_remoto.sh 192.168.1.50                    # ID = hostname, UDP 5000, cmd 5002
#      ./agente_remoto.sh 192.168.1.50 NODO_02            # ID explícito
#      ./agente_remoto.sh 192.168.1.50 NODO_02 5000 5002  # puertos explícitos
#
#  En el servidor central debe estar corriendo:
#      python3 server/server.py
#  y su firewall debe permitir UDP 5000 y TCP 5001 (ver README).
# =============================================================================
set -euo pipefail

# La raíz del proyecto. Si este archivo está instalado como symlink, hay que
# resolver el enlace antes de armar las rutas (igual que en el lanzador 'sdmr').
SRC="${BASH_SOURCE[0]}"
while [ -L "$SRC" ]; do
    DIR="$(cd -P "$(dirname "$SRC")" && pwd)"
    SRC="$(readlink "$SRC")"
    [[ "$SRC" != /* ]] && SRC="$DIR/$SRC"
done
RAIZ="$(cd -P "$(dirname "$SRC")/.." && pwd)"

if [ ! -f "$RAIZ/agent/agent.py" ]; then
    echo "ERROR: no encuentro 'agent/agent.py' en:"
    echo "    $RAIZ"
    echo "Este lanzador debe estar junto a client/, server/ y agent/."
    exit 1
fi

# ------------------------------ Argumentos -----------------------------------
if [ $# -lt 1 ] || [ "$1" = "-h" ] || [ "$1" = "--help" ]; then
    echo "Uso: $0 <IP_SERVIDOR> [ID_NODO] [PUERTO_UDP] [PUERTO_CMD]"
    echo
    echo "  IP_SERVIDOR  IP del equipo donde corre server/server.py (obligatorio)"
    echo "  ID_NODO      Identificador del nodo (por defecto: hostname de este equipo)"
    echo "  PUERTO_UDP   Puerto de telemetría del servidor (por defecto: 5000)"
    echo "  PUERTO_CMD   Puerto TCP de comandos EXEC de este agente (por defecto: 5002)"
    echo
    echo "Ejemplo: $0 192.168.1.50 NODO_02"
    exit 1
fi

IP_SERVIDOR="$1"
ID_NODO="${2:-$(hostname)}"
PUERTO_UDP="${3:-5000}"
PUERTO_CMD="${4:-5002}"

# Intérprete (se puede sobreescribir con la variable de entorno PYTHON)
PY="${PYTHON:-python3}"

if ! command -v "$PY" >/dev/null 2>&1; then
    echo "ERROR: no se encontró '$PY'. Instalá Python 3.8 o superior."
    exit 1
fi

echo "================================================================="
echo " SDMR - Agente Remoto"
echo "================================================================="
echo " Servidor central : $IP_SERVIDOR (UDP $PUERTO_UDP)"
echo " Nodo             : $ID_NODO"
echo " Canal EXEC local : TCP $PUERTO_CMD"
echo "================================================================="
echo " Asegurate de que el firewall del servidor permita UDP $PUERTO_UDP y"
echo " TCP 5001, y que ESTE equipo permita TCP $PUERTO_CMD (para EXEC)."
echo "-----------------------------------------------------------------"

exec "$PY" -u "$RAIZ/agent/agent.py" "$ID_NODO" "$IP_SERVIDOR" "$PUERTO_UDP" "$PUERTO_CMD"
