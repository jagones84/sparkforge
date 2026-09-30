#!/usr/bin/env python3
import json
import urllib.request

TOK = "REDACTED-COMPROMISED-TOKEN"


def get(url, tok=None):
    h = {"Authorization": "Bearer " + tok} if tok else {}
    return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=8).read())


st = get("http://127.0.0.1:8790/api/status", TOK)
print("sparkforge models:")
for m in st.get("models", []):
    print("  %-45s loaded=%s status=%s" % (m.get("alias"), m.get("loaded"), m.get("status")))
print("\nrouter models (native ids):")
try:
    rm = get("http://127.0.0.1:8080/v1/models")
    for m in rm.get("data", []):
        print("  %-45s status=%s" % (m.get("id"), (m.get("status") or {}).get("value")))
except Exception as e:
    print("  router error:", e)
