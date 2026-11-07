"""PyInstaller entry point (kept outside the package so the package's relative imports stay intact)."""
import multiprocessing
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from trafficlab.__main__ import main

if __name__ == "__main__":
    multiprocessing.freeze_support()          # needed for the process pool inside a frozen executable (and for Windows 'spawn')
    main()
