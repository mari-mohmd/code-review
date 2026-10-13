"""Locations used by the evaluation scripts.

Override with environment variables:
  INTENTCHECK_WORK  directory containing clones of pandapower/ and dronekit-python/
  INTENTCHECK_DATA  directory for evaluation data (default: ../data next to this file)
  INTENTCHECK_TOOL  IntentCheck.py to evaluate (default: this repository's)
"""
import os
from pathlib import Path

_here = Path(__file__).resolve().parent
WORK = os.environ.get("INTENTCHECK_WORK", str(_here.parents[2]))
EVAL = os.environ.get("INTENTCHECK_DATA", str(_here.parent / "data"))
TOOL = os.environ.get("INTENTCHECK_TOOL", str(_here.parents[1] / "IntentCheck.py"))
