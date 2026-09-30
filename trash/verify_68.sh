#!/bin/bash
cd /home/jagones/Repositories/sparkforge
python3 -m py_compile taskgraph.py server.py api_v02.py sandbox.py tools.py context_engine.py || { echo COMPILE_FAIL; exit 1; }
echo COMPILE_OK
systemctl --user restart sparkforge
sleep 5
echo -n "service: "; systemctl --user is-active sparkforge
python3 trash/test_cancel.py
