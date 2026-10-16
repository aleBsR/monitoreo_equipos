#!/usr/bin/env bash
# SDMR todo-en-uno Linux: servidor + gateway WS + web + 2 agentes
set -euo pipefail
cd "$(dirname "$0")"
PY="${PYTHON:-python3}"
if ! command -v "$PY" >/dev/null; then echo "Falta python3"; exit 1; fi
$PY -c "import websockets" 2>/dev/null || $PY -m pip install --user websockets
if [ ! -f web/dist/index.html ]; then (cd web && npm install --no-audit --no-fund && npm run build); fi
pkill -f "server/server.py" 2>/dev/null || true
pkill -f "server/gateway.py" 2>/dev/null || true
$PY -u server/server.py 5000 5001 & SRV=$!
sleep 2
$PY -u server/gateway.py 5003 127.0.0.1 5001 --serve-web & GW=$!
sleep 2
$PY -u agent/agent.py NODO_01 127.0.0.1 5000 5002 & A1=$!
$PY -u agent/agent.py NODO_02 127.0.0.1 5000 5004 & A2=$!
sleep 2
$PY -u verificar_red.py 127.0.0.1 5000 5001 5003 || true
echo "Web: http://127.0.0.1:5173  WS: ws://127.0.0.1:5003"
echo "Para cerrar: kill $SRV $GW $A1 $A2"
wait
