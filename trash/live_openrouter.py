#!/usr/bin/env python3
"""Live: keys loaded from .env + a real tiny OpenRouter call through the harness."""
import json
import sys
import urllib.request

sys.path.insert(0, "/home/jagones/Repositories/sparkforge")
import providers  # noqa: E402
import server  # noqa: E402

for pid in ("openrouter", "deepseek"):
    p = providers.get(pid)
    k = providers.api_key(p)
    print("%-11s key_env=%s present=%s len=%s" % (
        pid, p.get("api_key_env"), bool(k), len(k or "")))

ref = "openrouter:z-ai/glm-5.3-flash"
url, headers, mid = providers.endpoint(ref)
print("endpoint:", url, "model:", mid, "auth:", "Authorization" in headers)

body = json.dumps({"model": mid, "messages": [{"role": "user", "content": "Rispondi in italiano: spiega in una frase cosa sei."}],
                   "max_tokens": 400, "stream": False}).encode()
req = urllib.request.Request(url, data=body, headers=headers)
try:
    with urllib.request.urlopen(req, timeout=90) as r:
        data = json.loads(r.read().decode())
    msg = (data.get("choices") or [{}])[0].get("message") or {}
    print("PASS openrouter live call ->", repr((msg.get("content") or "")[:80]))
except Exception as e:  # noqa: BLE001
    print("FAIL openrouter live call ::", str(e)[:200])
