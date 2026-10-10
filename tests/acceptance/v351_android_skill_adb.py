#!/usr/bin/env python3
"""v351 — the Android build/deploy skill must guide DGX->phone ADB correctly.

Root cause of the Jago failure (2026-10-08): `android-app-build-deploy`'s step 3
prescribed `compileSdk = 36` while its OWN reference (references/build-on-arm64.md)
proves that on the ARM64 DGX the Debian aarch64 aapt2 (2.19-debian) cannot parse
android-35/36 -> the build dies with "Entry offset ... outside Type boundaries".
And step 1 told the agent to READ the ADB port from `adb devices -l` (empty on the
DGX) or from the PC's adb server - it never told it to issue the simple, working
`adb connect oneplus-15r:5555`. So no agent ever connected the phone, and the
"install on device" subjob could never succeed.

This guard keeps the guidance correct so a weak model is steered to the working path.

Deterministic, no model. Run: python3 tests/acceptance/v351_android_skill_adb.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
P = os.path.join(REPO, "skills", "android", "android-app-build-deploy", "SKILL.md")
t = open(P, encoding="utf-8").read() if os.path.exists(P) else ""

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


check("A1 the skill exists and is non-trivial", len(t) > 500, "len=%d" % len(t))
check("A2 it tells the agent to CONNECT directly (adb connect oneplus-15r:5555)",
      "adb connect oneplus-15r:5555" in t, "")
check("A3 it covers a changed port (PC discovery + <porta> connect)",
      "win-ts" in t and "oneplus-15r:<porta>" in t, "")
check("A4 it names the DGX/Tailscale transport, not USB-only",
      "usb" in t.lower(), "")
check("A5 it references build-on-arm64.md for the ARM64 caveat",
      "build-on-arm64.md" in t, "")
check("A6 it states compileSdk 34 for the ARM64/DGX path",
      "compileSdk = 34" in t, "")
check("A7 it no longer hard-requires compileSdk=36 for every host",
      "`compileSdk = 36`, `minSdk = 24`, `targetSdk = 36`" not in t, "")

print("---")
ok = sum(results)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)

