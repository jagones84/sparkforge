#!/bin/bash
cd /home/jagones/Repositories/sparkforge
set -a
. "$HOME/.config/sparkforge/env"
set +a
echo "--- v02_acceptance ---"
python3 tests/v02_acceptance.py 2>&1 | tail -n 30
