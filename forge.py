#!/usr/bin/env python3
"""SparkForge CLI shim — keeps `python3 forge.py ...` working."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from sparkforge.forge import main  # noqa: E402

if __name__ == "__main__":
    main()
