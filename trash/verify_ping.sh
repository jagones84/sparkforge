#!/bin/bash
# Verify the SSE keepalive: an agent run blocked on an approval must keep the
# channel alive with ": ping" comment frames.
TOKEN=REDACTED-COMPROMISED-TOKEN
timeout 45 curl -N -s -H "Authorization: Bearer $TOKEN" \
  "http://127.0.0.1:8790/api/agent/run?goal=usa%20il%20tool%20shell%20per%20eseguire%20mkdir%20pingtest&max_steps=3" \
  > /tmp/sse_ping.out 2>&1
echo "--- ping count ---"
grep -c ": ping" /tmp/sse_ping.out
echo "--- events seen ---"
grep -a "^event:" /tmp/sse_ping.out | sort | uniq -c
