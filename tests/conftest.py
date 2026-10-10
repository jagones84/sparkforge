"""Test configuration for pytest.

Puts the package on `sys.path` so `import longrun` works from any test under
`tests/` WITHOUT installing the package. Root cause of JAG-313: the property
tests were collected but could not import `longrun` (no src on sys.path), so
`pytest tests/properties/` errored on collection and the nightly loop silently
reported `props_exit=2` for hours — the property tests never actually ran.
"""
import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = os.path.join(_REPO, "src")
if os.path.isdir(_SRC) and _SRC not in sys.path:
    sys.path.insert(0, _SRC)

