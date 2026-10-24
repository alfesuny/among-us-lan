"""Among Us LAN — start the game.

    python main.py

One player clicks HOST GAME, everyone else on the same network clicks JOIN GAME.
"""
import os
import sys

if sys.version_info < (3, 8):
    sys.exit("Python 3.8 or newer is required.")

# Assets are found relative to this file, but keep the working directory sane too.
os.chdir(os.path.dirname(os.path.abspath(__file__)))

try:
    import pygame  # noqa: F401
except ImportError:
    sys.exit("pygame is not installed. Run:  python -m pip install -r requirements.txt")

from amongus.client.app import main  # noqa: E402

if __name__ == "__main__":
    main()
