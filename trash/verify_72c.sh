#!/bin/bash
cd /home/jagones/Repositories/sparkforge
python3 -m py_compile server.py context_engine.py memory.py providers.py || { echo COMPILE_FAIL; exit 1; }
echo COMPILE_OK
echo "== v06 timing (regression check) =="
start=$(date +%s)
out=$(timeout 180 python3 tests/v06_taskgraph.py 2>&1); rc=$?
end=$(date +%s)
echo "rc=$rc secs=$((end-start)) :: $(printf '%s\n' "$out" | tail -n 1)"
echo "== memory search latency (should be < 1s after the first probe) =="
python3 - <<'PY'
import time, sys
sys.path.insert(0, '.')
import memory
t0=time.time(); memory.search("context budget auto compaction harness", None, 3, True); d1=time.time()-t0
t0=time.time(); memory.search("provider model routing", None, 3, True); d2=time.time()-t0
print("first=%.3fs second=%.3fs" % (d1, d2))
print("vector_index=%s" % (memory.stats().get("vector_index")))
PY
