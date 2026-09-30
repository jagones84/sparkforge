#!/bin/bash
cd /home/jagones/Repositories/sparkforge
python3 -m py_compile providers.py server.py || { echo COMPILE_FAIL; exit 1; }
echo COMPILE_OK
echo "== v075 providers acceptance =="
python3 tests/v075_providers.py
echo "== restart + live catalogue =="
systemctl --user restart sparkforge
sleep 5
echo -n "service: "; systemctl --user is-active sparkforge
curl -s -H "Authorization: Bearer REDACTED-COMPROMISED-TOKEN" "http://127.0.0.1:8790/api/providers" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print('count=%s default=%s' % (d.get('count'), d.get('default'))); [print(' -', p['id'], p['name'], 'available=%s' % p['available'], 'models=%d' % len(p['models'])) for p in d['providers']]"
