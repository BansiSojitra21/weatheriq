"""WeatherIQ FastAPI application package."""

from __future__ import annotations

import sys
from pathlib import Path

_here = Path(__file__).resolve()
for _parent in _here.parents:
    if (_parent / "pyproject.toml").exists() and (_parent / "ml").exists():
        _root = str(_parent)
        if _root not in sys.path:
            sys.path.insert(0, _root)
        break
