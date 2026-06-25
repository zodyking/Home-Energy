"""Shared atomic JSON file load/save helpers for all persistent stores.

Consolidates atomic write pattern (tmp file + replace) used by:
- config_manager.py
- room_ratings.py
- zone_health_storage.py
- efficiency_digest.py
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

_LOGGER = logging.getLogger(__name__)


def load_json(path: str | Path, *, default: Any = None) -> Any:
    """Load JSON from path, returning default if file missing or invalid."""
    path = Path(path)
    if not path.exists():
        return default() if callable(default) else (default if default is not None else {})
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        return raw
    except (OSError, json.JSONDecodeError) as e:
        _LOGGER.warning("JSON load failed %s: %s", path, e)
        return default() if callable(default) else (default if default is not None else {})


def atomic_save_json(path: str | Path, data: Any, *, indent: int = 2) -> bool:
    """Atomically save JSON via tmp file + replace. Returns True on success."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=indent)
        tmp.replace(path)
        return True
    except OSError as e:
        _LOGGER.warning("JSON save failed %s: %s", path, e)
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return False
