#!/usr/bin/env python3
"""v0.7.5 acceptance — providers catalogue + model routing (JAG-71).

Offline: proves the catalogue lists the DGX/Windows llama.cpp, vLLM, OpenRouter
and DeepSeek providers, that `<provider>:<model>` resolves to the right endpoint
and headers, and that the requested families (GLM flash, DeepSeek flash) are
listed. No key is read, printed or required.
"""
import os
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))
from sparkforge import providers  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


ids = {p["id"] for p in providers.providers()}
check("P1 providers declared (dgx, win, vllm, openrouter, deepseek)",
      {"dgx", "win", "vllm", "openrouter", "deepseek"} <= ids, "ids=%s" % sorted(ids))

cat = providers.catalog()
total = cat["count"]
check("P2 catalogue exposes every model", total >= 25, "models=%d" % total)

orx = providers.get("openrouter")
orx_models = [m["id"] for m in orx["models"]]
check("P3 OpenRouter lists GLM-flash and DeepSeek-flash families",
      any("glm" in m and "flash" in m for m in orx_models)
      and any("deepseek" in m and "flash" in m for m in orx_models),
      "sample=%s" % orx_models[:6])

ds = providers.get("deepseek")
check("P4 DeepSeek original provider has deepseek-chat + deepseek-reasoner",
      {m["id"] for m in ds["models"]} == {"deepseek-chat", "deepseek-reasoner"},
      "models=%s" % [m["id"] for m in ds["models"]])

win = providers.get("win")
check("P5 Windows llama.cpp provider points at the Tailscale host",
      win["base_url"].startswith("http://100.76.251.9"), win["base_url"])

hit = providers.resolve("dgx:glm-5.3-flash-iq2")
check("P6 `<provider>:<model>` resolves to the provider",
      hit is not None and hit[0]["id"] == "dgx" and hit[1] == "glm-5.3-flash-iq2",
      "hit=%s" % (hit[1] if hit else None))

url, headers, mid = providers.endpoint("openrouter:z-ai/glm-5.3-flash")
check("P7 endpoint builds the provider URL and model id",
      url == "https://openrouter.ai/api/v1/chat/completions"
      and mid == "z-ai/glm-5.3-flash" and "Content-Type" in headers,
      "url=%s model=%s" % (url, mid))

hit2 = providers.resolve("deepseek/deepseek-v4.1-flash:batch")
check("P8 ':' inside a model id is not mis-split as a provider",
      hit2 is not None and hit2[0]["id"] == "openrouter"
      and hit2[1] == "deepseek/deepseek-v4.1-flash:batch",
      "hit=%s" % (hit2[1] if hit2 else None))

bare = providers.resolve("glm-5.3-flash-iq2")
check("P9 a bare model id resolves (local first)",
      bare is not None and bare[0]["id"] == "dgx", "hit=%s" % (bare[0]["id"] if bare else None))

check("P10 no secret is stored in the config (keys are env references only)",
      all((p.get("api_key_env") or "") == "" or (p.get("api_key_env") or "").isupper()
          for p in providers.providers())
      and not any("sk-" in str(p) for p in providers.providers()),
      "key_envs=%s" % [p.get("api_key_env") for p in providers.providers()])

# JAG-72: the remote max context comes from LIVE vendor metadata, not a guess.
providers._OPENROUTER_CTX.update(ts=time.time(), map={"z-ai/glm-5.3-flash": 202752})
check("P11 openrouter window resolved from live metadata",
      providers.context_length("openrouter:z-ai/glm-5.3-flash") == 202752,
      "got=%s" % providers.context_length("openrouter:z-ai/glm-5.3-flash"))
check("P12 catalogue exposes the resolved remote window",
      any(m["context_length"] == 202752
          for p in providers.catalog()["providers"] if p["id"] == "openrouter"
          for m in p["models"] if m["id"] == "z-ai/glm-5.3-flash"))

print("\n==== %d/%d checks passed ====" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)