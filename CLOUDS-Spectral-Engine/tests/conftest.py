"""Pytest path setup: repo root (clouds_link, spectro), flight/pi, gse."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, "flight", "pi"), os.path.join(ROOT, "gse")):
    if p not in sys.path:
        sys.path.insert(0, p)
