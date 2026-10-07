#!/usr/bin/env python3
"""v247 — wire type-confusion on the providers/rules/workspace surface
(JAG-247..250).

These functions take JSON bodies / query strings straight from the client. A
non-string `id`, `model`, `path` or `ref` used to reach `.strip()`/`int()`/`dict()`
and raise, which the HTTP layer surfaced as a DROPPED connection (no response):

  JAG-247  providers.upsert_provider  -> int id hit `.strip()` (AttributeError)
  JAG-248  providers.add_model        -> non-str model / "abc" context_length
  JAG-249  rules.set_workspace        -> non-str path hit `.strip()`
  JAG-250  providers.upsert_provider  -> `models:[1,2]` hit `dict(1)` (TypeError)

Deterministic, no live server, no network, and NEVER touches the live config:
the provider overlay + config dir are redirected to a throwaway temp dir.
Run:  python3 tests/v247_api_types.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v247-")
os.environ["SPARKFORGE_PROVIDERS_LOCAL"] = os.path.join(TMP, "providers.local.yaml")
os.environ["SPARKFORGE_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["SPARKFORGE_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
sys.path.insert(0, os.path.join(REPO, "src"))

from sparkforge import providers, rules  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def nocall(fn, *a, **k):
    """Return (raised, value). The functions must never raise on wire garbage."""
    try:
        return None, fn(*a, **k)
    except Exception as e:  # noqa: BLE001
        return repr(e), None


# ---- JAG-247: provider id must be a string --------------------------------
for bad in (123, ["x"], {"a": 1}, None, True):
    err, res = nocall(providers.upsert_provider, {"id": bad})
    check("JAG-247 upsert_provider(id=%r) -> no raise + ok False" % (bad,),
          err is None and isinstance(res, dict) and res.get("ok") is False,
          err or str(res))

err, res = nocall(providers._validate_provider, {"id": "OK_UP"})
check("JAG-247 _validate_provider rejects uppercase id",
      err is None and res is not None, err or str(res))

err, res = nocall(providers.upsert_provider, {"id": "jagv247", "kind": "nope"})
check("JAG-247 bad kind -> ok False",
      err is None and res.get("ok") is False, err or str(res))

err, res = nocall(providers.upsert_provider, {"id": "jagv247", "base_url": "ftp://x"})
check("JAG-247 bad base_url -> ok False",
      err is None and res.get("ok") is False, err or str(res))

# ---- JAG-250: models must be a list of ids/objects ------------------------
err, res = nocall(providers.upsert_provider,
                  {"id": "jagv247", "kind": "openai", "models": [1, 2]})
check("JAG-250 models=[1,2] -> ok True (coerced)",
      err is None and res.get("ok") is True, err or str(res))
err, res = nocall(providers.upsert_provider, {"id": "jagv247", "models": "x"})
check("JAG-250 models='x' -> ok False",
      err is None and res.get("ok") is False, err or str(res))
err, res = nocall(providers.upsert_provider, {"id": "jagv247", "models": [[1]]})
check("JAG-250 models=[[1]] -> ok False",
      err is None and res.get("ok") is False, err or str(res))

# ---- JAG-248: add_model / remove_model / set_default coerce wire values ----
err, res = nocall(providers.add_model, "jagv247", 123)
check("JAG-248 add_model(model=123) -> ok True",
      err is None and res.get("ok") is True, err or str(res))
err, res = nocall(providers.add_model, "jagv247", "m1", "abc")
check("JAG-248 add_model(context_length='abc') -> ok False",
      err is None and res.get("ok") is False, err or str(res))
err, res = nocall(providers.add_model, "jagv247", None)
check("JAG-248 add_model(model=None) -> ok False",
      err is None and res.get("ok") is False, err or str(res))
err, res = nocall(providers.remove_model, "jagv247", 123)
check("JAG-248 remove_model(model=123) -> ok True",
      err is None and res.get("ok") is True, err or str(res))
err, res = nocall(providers.set_default, 123)
check("JAG-248 set_default(ref=123) -> ok True",
      err is None and res.get("ok") is True, err or str(res))
err, res = nocall(providers.set_default, None)
check("JAG-248 set_default(ref=None) -> ok False",
      err is None and res.get("ok") is False, err or str(res))

# ---- JAG-249: rules path coercion -----------------------------------------
for bad in (123, None, {"a": 1}):
    err, res = nocall(rules._win_to_posix, bad)
    check("JAG-249 _win_to_posix(%r) -> no raise" % (bad,), err is None, err or "")
    err, res = nocall(rules.set_workspace, bad)
    check("JAG-249 set_workspace(%r) -> ok False" % (bad,),
          err is None and res.get("ok") is False, err or str(res))

# ---- static guards --------------------------------------------------------
def read(rel):
    with open(os.path.join(REPO, "src", "sparkforge", rel), encoding="utf-8") as f:
        return f.read()


pv = read("providers.py")
rv = read("rules.py")
av = read("api_v02.py")
sv = read("server.py")
check("JAG-247 providers guards id type", "not isinstance(pid, str)" in pv)
check("JAG-248 providers ints context_length", "context_length must be an integer" in pv)
check("JAG-250 providers validates models list", "models must be a list" in pv)
check("JAG-249 rules guards path type", "not isinstance(path, str)" in rv)
for rel, txt in (("rules.py", rv), ("api_v02.py", av), ("server.py", sv),
                 ("providers.py", pv)):
    for bad in ("cartella inesistente", "sessione inesistente"):
        check("i18n %s free of '%s'" % (rel, bad), bad not in txt)

print("---")
ok = sum(results)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
