#!/bin/bash
set -euo pipefail
STATION_HOME=$(cd -- "$(dirname -- "$0")" && pwd)
export FIT_LAB_DATA_ROOT="$STATION_HOME/data"
export FIT_LAB_EMBEDDED_RECEIVER=1
export FIT_LAB_FULLSCREEN=1
export FIT_LAB_NATIVE_VIDEO=${FIT_LAB_NATIVE_VIDEO:-1}
export FIT_LAB_ROOT="$STATION_HOME"
export PYTHONPATH="$STATION_HOME/runtime:$STATION_HOME/source${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONPYCACHEPREFIX="$STATION_HOME/data/cache/python"
mkdir -p "$FIT_LAB_DATA_ROOT/logs" "$FIT_LAB_DATA_ROOT/cache"
cd "$STATION_HOME/source"
/usr/bin/python3 -m receiver.control_install >> "$FIT_LAB_DATA_ROOT/logs/control-service-install.log" 2>&1 || true
exec /usr/bin/python3 -m master.gui "$@" >> "$FIT_LAB_DATA_ROOT/logs/application.log" 2>&1
