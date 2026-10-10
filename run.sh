#!/usr/bin/env bash
# Longrun launcher — WebUI + API (+ mobile if --host 0.0.0.0)
cd "$(dirname "$0")"
exec python3 server.py "$@"
