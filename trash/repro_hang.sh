#!/usr/bin/env bash
# Repro: does /api/chat/stream write_todos then hang? Timestamp every SSE line.
set -u
TOK="REDACTED-COMPROMISED-TOKEN"
SID="repro-$(date +%s)"
BASE="http://127.0.0.1:8790/api/chat/stream"
MSG="analizza il repository sparkforge e proponi 3 miglioramenti"
echo "START $(date +%s) session=${SID}"
curl -sN --max-time 150 -H "Authorization: Bearer ${TOK}" \
  --get --data-urlencode "message=${MSG}" --data-urlencode "session=${SID}" "${BASE}" \
  | while IFS= read -r line; do printf '[%s] %s\n' "$(date +%s)" "${line}"; done
echo "END $(date +%s)"
