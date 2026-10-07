"""Orbit — SparkForge beta command deck (fully detachable).

This package is an OPTIONAL, self-contained beta layer that lives OUTSIDE the main
app (`src/`). The application only ever reaches it through two guarded hooks in
`sparkforge.server` (`serve_page` before auth, `handle` after auth). If this whole
`src2/` folder is deleted — or fails to import — the app is completely unaffected.

Design is object-oriented, one concern per class:
  * ModelBay        — the FULL provider/model catalogue (every provider, not just DGX)
  * SessionRegistry — the roster of sessions + pre-provisioning ("hire ahead")
  * Orchestrator    — dispatch a goal to one or many sessions, in the background
  * ConsolePage     — serves the single-file UI (`web/orbit.html`)

Nothing here writes into the main app's modules; it only consumes their public
functions. That is what makes it droppable.
"""
from .api import serve_page, handle  # noqa: F401

__all__ = ["serve_page", "handle"]
