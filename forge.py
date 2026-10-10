#!/usr/bin/env python3
"""Longrun CLI shim — keeps `python3 forge.py ...` working."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from longrun.forge import main  # noqa: E402

if __name__ == "__main__":
    main()
