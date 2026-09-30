#!/bin/bash
cd /home/jagones/Repositories/sparkforge
python3 -m py_compile taskgraph.py server.py api_v02.py || { echo COMPILE_FAIL; exit 1; }
echo COMPILE_OK
systemctl --user restart sparkforge
sleep 5
python3 tests/v06_taskgraph.py 2>&1 | tail -n 50
