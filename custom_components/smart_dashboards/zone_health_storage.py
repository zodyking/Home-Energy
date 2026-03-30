"""Persistent zone-health snapshot store under Home Assistant config ``data/``."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)

SCHEMA_VERSION = 1
FILENAME = "smart_dashboards_zone_health.json"


def zone_health_store_path(hass: HomeAssistant) -> Path:
    """Path to the zone-health JSON file (``<config>/data/...``)."""
    return Path(hass.config.path("data")) / FILENAME


def default_store() -> dict[str, Any]:
    return {"version": SCHEMA_VERSION, "persons": {}}


def load_store(path: Path) -> dict[str, Any]:
    if not path.exists():
        return default_store()
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, dict):
            return default_store()
        if not isinstance(raw.get("persons"), dict):
            raw["persons"] = {}
        raw.setdefault("version", SCHEMA_VERSION)
        return raw
    except (OSError, json.JSONDecodeError) as e:
        _LOGGER.warning("Zone health store load failed %s: %s", path, e)
        return default_store()


def save_store(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        tmp.replace(path)
    except OSError as e:
        _LOGGER.warning("Zone health store save failed %s: %s", path, e)
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def ensure_person_entry(
    persons: dict[str, Any], person_key: str, now: datetime
) -> dict[str, Any]:
    pk = str(person_key).strip().lower()
    p = persons.get(pk)
    if not isinstance(p, dict):
        p = {"warmup_started": now.isoformat(), "snapshots": []}
        persons[pk] = p
        return p
    if not p.get("warmup_started"):
        p["warmup_started"] = now.isoformat()
    if not isinstance(p.get("snapshots"), list):
        p["snapshots"] = []
    return p


def prune_snapshots(person_entry: dict[str, Any], cutoff: datetime) -> None:
    snaps = person_entry.get("snapshots")
    if not isinstance(snaps, list):
        person_entry["snapshots"] = []
        return
    kept: list[dict[str, Any]] = []
    for item in snaps:
        if not isinstance(item, dict):
            continue
        ts_raw = item.get("ts")
        if not ts_raw:
            continue
        ts = dt_util.parse_datetime(str(ts_raw))
        if ts is None or ts < cutoff:
            continue
        kept.append(item)
    person_entry["snapshots"] = kept


def append_snapshot(
    person_entry: dict[str, Any], states: set[str], now: datetime
) -> None:
    snaps = person_entry.setdefault("snapshots", [])
    snaps.append({"ts": now.isoformat(), "states": sorted(states)})


def union_states_from_snapshots(person_entry: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    snaps = person_entry.get("snapshots")
    if not isinstance(snaps, list):
        return out
    for item in snaps:
        if not isinstance(item, dict):
            continue
        st = item.get("states")
        if isinstance(st, list):
            out.update(str(x).strip().lower() for x in st if x)
    return out


def warmup_complete(
    person_entry: dict[str, Any], now: datetime, history_days: int
) -> bool:
    ws = person_entry.get("warmup_started")
    if not ws:
        return False
    start = dt_util.parse_datetime(str(ws))
    if start is None:
        return False
    return (now - start) >= timedelta(days=history_days)


def warmup_complete_at_iso(
    person_entry: dict[str, Any], history_days: int
) -> str | None:
    ws = person_entry.get("warmup_started")
    if not ws:
        return None
    start = dt_util.parse_datetime(str(ws))
    if start is None:
        return None
    return (start + timedelta(days=history_days)).isoformat()
