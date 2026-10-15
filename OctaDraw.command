#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 nordseele
# OctaDraw: double-click in the Finder (or ./OctaDraw.command in a terminal).
# Opens http://127.0.0.1:8077; closing the Terminal window stops OctaDraw. PORT=8078 ./OctaDraw.command for another port.
cd "$(dirname "$0")" || exit 1
PORT=${PORT:-8077}
PY=python3; [ -x .venv/bin/python ] && PY=.venv/bin/python
# A running OctaDraw keeps its old code: replace it. Anything else on the port: stop.
for pid in $(lsof -ti tcp:$PORT -sTCP:LISTEN); do
  if ps -o command= -p "$pid" | grep -q octadraw.py; then
    kill "$pid"; sleep 0.5
  else
    echo "Port $PORT is used by another program ($(ps -o command= -p "$pid"))."; exit 1
  fi
done
[ -z "$NO_OPEN" ] && (sleep 1; open "http://127.0.0.1:$PORT/") &
echo "OctaDraw: http://127.0.0.1:$PORT/  (close this window to stop it)"
exec "$PY" octadraw.py --port "$PORT"
