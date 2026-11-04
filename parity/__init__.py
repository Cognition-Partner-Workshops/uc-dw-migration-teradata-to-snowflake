"""Parity harness for converted banking objects."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SNOWFLAKE = str(ROOT / "snowflake")
if SNOWFLAKE not in sys.path:
    sys.path.insert(0, SNOWFLAKE)
