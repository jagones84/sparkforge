#!/usr/bin/env python3
"""v0.9.18 acceptance — providers/models are user-editable, without secrets in the repo (JAG-112).

The base config/providers.yaml is versioned and static; user additions land in a
gitignored overlay (config/providers.local.yaml) that is merged over the base.
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp(prefix="sf-prov-")
os.environ["SPARKFORGE_SESSIONS_DIR"] = os.path.join(tmp, "sessions")
os.environ["SPARKFORGE_DB"] = os.path.join(tmp, "events.db")
os.environ["SPARKFORGE_GRAPH_DIR"] = os.path.join(tmp, "graphs")
os.makedirs(os.environ["SPARKFORGE_SESSIONS_DIR"], exist_ok=True)
os.makedirs(os.environ["SPARKFORGE_GRAPH_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from sparkforge import api_v02  # noqa: E402
from sparkforge import providers as P  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


BASE = os.path.join(tmp, "providers.yaml")
LOCAL = os.path.join(tmp, "providers.local.yaml")
with open(BASE, "w", encoding="utf-8") as f:
    f.write('version: "1"\n'
            "default: base:mA\n"
            "providers:\n"
            "  - id: base\n"
            "    name: Base\n"
            "    kind: openai\n"
            "    base_url: http://127.0.0.1:9/v1\n"
            "    models:\n"
            "      - {id: mA}\n"
            "      - {id: mB}\n")
P.CONFIG = BASE
P.LOCAL_CONFIG = LOCAL
P._cache.update(ts=None, cfg=None)


def local_text():
    try:
        with open(LOCAL, "r", encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


# ---- P1: upsert a NEW provider ---------------------------------------------
r = P.upsert_provider({"id": "newp", "name": "New P", "kind": "openai",
                       "base_url": "https://api.example.com/v1",
                       "api_key_env": "NEWP_API_KEY",
                       "models": [{"id": "x1", "context_length": 32000}]})
P._cache.update(ts=None, cfg=None)
check("P1 upsert ok", r.get("ok") is True, str(r))
check("P1b new provider in the merged config", P.get("newp") is not None)
check("P1c written to the local overlay", "newp" in local_text())

# ---- P2: override a BASE provider field (base file untouched) --------------
P.upsert_provider({"id": "base", "name": "Base Renamed"})
P._cache.update(ts=None, cfg=None)
with open(BASE, "r", encoding="utf-8") as f:
    base_txt = f.read()
check("P2 override applies", (P.get("base") or {}).get("name") == "Base Renamed")
check("P2b base file untouched", "Base Renamed" not in base_txt)

# ---- P3: add / remove a model on a BASE provider ---------------------------
P.add_model("base", "mC", context_length=1000)
P._cache.update(ts=None, cfg=None)
ids = [m["id"] for m in P.get("base")["models"]]
check("P3 add_model on base", "mC" in ids, str(ids))
mc = next((m for m in P.get("base")["models"] if m["id"] == "mC"), {})
check("P3b context length stored", mc.get("context_length") == 1000, str(mc))
P.remove_model("base", "mB")
P._cache.update(ts=None, cfg=None)
ids2 = [m["id"] for m in P.get("base")["models"]]
check("P3c remove_model tombstones a base model", "mB" not in ids2 and "mA" in ids2, str(ids2))
with open(BASE, "r", encoding="utf-8") as f:
    check("P3d base file still lists mB", "mB" in f.read())

# ---- P4: remove_provider ---------------------------------------------------
P.remove_provider("newp")
P._cache.update(ts=None, cfg=None)
check("P4 local-only provider removed", P.get("newp") is None)
P.remove_provider("base")
P._cache.update(ts=None, cfg=None)
check("P4b base provider disabled (not in view)", P.get("base") is None)
with open(BASE, "r", encoding="utf-8") as f:
    check("P4c base file still has the provider", "id: base" in f.read())

# ---- P5: set_default -------------------------------------------------------
r5 = P.set_default("base:mC")
P._cache.update(ts=None, cfg=None)
check("P5 set_default ok", r5.get("ok") is True, str(r5))
check("P5b default_ref updated", P.default_ref() == "base:mC", str(P.default_ref()))

# ---- P6: validation --------------------------------------------------------
check("P6 bad id rejected", P.upsert_provider({"id": "Bad Id!"}).get("ok") is False)
check("P6b bad base_url rejected",
      P.upsert_provider({"id": "ok1", "base_url": "ftp://x"}).get("ok") is False)
check("P6c secret-looking api_key_env rejected",
      P.upsert_provider({"id": "ok2", "api_key_env": "sk-abc123"}).get("ok") is False)

# ---- P7: no secret is ever written to the repo -----------------------------
P.upsert_provider({"id": "ok3", "base_url": "https://api.example.com/v1",
                   "api_key_env": "OK3_KEY"})
txt = local_text()
check("P7 overlay stores the env NAME, not a value",
      "OK3_KEY" in txt and "sk-" not in txt and "Bearer" not in txt)

# ---- P8: API helpers exist -------------------------------------------------
names = ("provider_upsert", "provider_remove", "provider_add_model",
         "provider_remove_model", "provider_set_default", "provider_reload")
check("P8 api helpers present", all(hasattr(api_v02, n) for n in names),
      str([n for n in names if not hasattr(api_v02, n)]))

total = len(results)
passed = sum(results)
print("\n==== %d/%d checks passed ====" % (passed, total))
sys.exit(0 if passed == total else 1)
