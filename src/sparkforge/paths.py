"""Central filesystem anchors for the SparkForge package (JAG-181).

Every module imports its paths from here instead of deriving them from its own
``__file__``, so moving a module inside the package never changes which repo
directory (data, config, skills, webui) it reads.
"""
import os

# src/sparkforge/paths.py -> src/sparkforge -> src -> <repo root>
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(REPO_ROOT, "data")
