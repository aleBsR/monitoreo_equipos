#!/usr/bin/env bash
# Lanzador de un click: abre la mini interfaz de control del agente (Linux).
set -euo pipefail
SRC="${BASH_SOURCE[0]}"
while [ -L "$SRC" ]; do
    DIR="$(cd -P "$(dirname "$SRC")" && pwd)"
    SRC="$(readlink "$SRC")"
    [[ "$SRC" != /* ]] && SRC="$DIR/$SRC"
done
RAIZ="$(cd -P "$(dirname "$SRC")/../.." && pwd)"
PY="${PYTHON:-python3}"
exec "$PY" "$RAIZ/scripts/agent/agent_control.py"
