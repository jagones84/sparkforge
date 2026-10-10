#!/usr/bin/env python3
"""Longrun MCP stdio server shim - keeps `python3 mcp_server.py` working."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from longrun.interop.mcp_server import main  # noqa: E402

if __name__ == "__main__":
    main()

