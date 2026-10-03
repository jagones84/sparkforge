#!/usr/bin/env python3
"""SparkForge launcher shim.

Keeps the documented entrypoint (`python3 server.py`), the systemd ExecStart and
run.sh / run.ps1 valid after the code moved into the `sparkforge` package.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from sparkforge.server import main  # noqa: E402

if __name__ == "__main__":
    main()
