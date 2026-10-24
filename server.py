"""Dedicated Among Us LAN server (optional: the game can also host from its menu).

    python server.py [--port 4321] [--name "Friday night"]
"""
import os
import sys

os.chdir(os.path.dirname(os.path.abspath(__file__)))

from amongus.server import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
