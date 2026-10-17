"""History that routine cleanup must not delete.

Daily energy, person/device-tracker presence, and last-online timestamps live
here. Retention jobs that trim intraday charts, the 45-day totals file, and
the event archive do not touch this store.
"""
from __future__ import annotations

import logging
from typing import Any

from .json_store import atomic_save_json, load_json

_LOGGER = logging.getLogger(__name__)

SCHEMA_VERSION = 1
FILENAME = "durable_history.json"

_OFFLINE_STATES = frozenset({"", "unknown", "unavailable", "none"})
_APPLIANCE_TYPES = frozenset(
    {
        "outlet",
        "single_outlet",
        "light",
        "vent",
        "wall_heater",
        "minisplit",
        "stove",
        "microwave",
        "fridge",
    }
)


def _default_store() -> dict[str, Any]:
    return {"version": SCHEMA_VERSION, "availability": {}, "days": {}}


def _day_bucket(days: dict[str, Any], day: str) -> dict[str, Any]:
    bucket = days.get(day)
    if not isinstance(bucket, dict):
        bucket = {"rooms": {}, "persons": {}, "totals": {}}
        days[day] = bucket
    if not isinstance(bucket.get("rooms"), dict):
        bucket["rooms"] = {}
    if not isinstance(bucket.get("persons"), dict):
        bucket["persons"] = {}
    if not isinstance(bucket.get("totals"), dict):
        bucket["totals"] = {}
    return bucket


def room_id_of(room: dict) -> str:
    rid = room.get("id")
    if rid is not None and str(rid).strip():
        return str(rid).strip()
    return str(room.get("name") or "").strip().lower().replace(" ", "_")


def watch_entities(outlet: dict | None) -> list[tuple[str, str]]:
    """HA entities whose unavailable state means this appliance is offline."""
    if not isinstance(outlet, dict):
        return []
    otype = str(outlet.get("type") or "outlet").strip().lower()
    if otype not in _APPLIANCE_TYPES:
        return []

    found: list[tuple[str, str]] = []

    def add(entity_id: Any, part: str) -> None:
        eid = str(entity_id or "").strip()
        if not eid or "." not in eid:
            return
        found.append((eid, part))

    if otype == "outlet":
        add(outlet.get("plug1_entity"), "Plug 1")
        add(outlet.get("plug2_entity"), "Plug 2")
        add(outlet.get("plug1_switch"), "Plug 1 switch")
        add(outlet.get("plug2_switch"), "Plug 2 switch")
    elif otype == "light":
        add(outlet.get("switch_entity"), "Room switch")
        if outlet.get("power_source") == "sensor":
            add(outlet.get("power_sensor_entity"), "Power sensor")
        for row in outlet.get("light_entities") or []:
            if isinstance(row, dict):
                add(row.get("entity_id"), "Light")
            elif isinstance(row, str):
                add(row, "Light")
    elif otype in ("vent", "wall_heater"):
        add(outlet.get("switch_entity"), "Switch")
        if outlet.get("power_source") == "sensor":
            add(outlet.get("power_sensor_entity"), "Power sensor")
    elif otype in ("single_outlet", "minisplit", "stove", "microwave", "fridge"):
        add(outlet.get("plug1_entity"), "Power")
        add(outlet.get("plug1_switch"), "Switch")
        if outlet.get("power_source") == "sensor":
            add(outlet.get("power_sensor_entity"), "Power sensor")

    deduped: list[tuple[str, str]] = []
    seen: set[str] = set()
    for eid, part in found:
        if eid in seen:
            continue
        seen.add(eid)
        deduped.append((eid, part))
    return deduped


def entity_is_online(state: str | None) -> bool:
    return str(state or "").strip().lower() not in _OFFLINE_STATES


class DurableHistory:
    """Append-only daily ledger plus last-online map. No prune method."""

    def __init__(self, path: str) -> None:
        self.path = path
        self.data: dict[str, Any] = _default_store()

    def load(self) -> None:
        raw = load_json(self.path, default=_default_store)
        if not isinstance(raw, dict):
            self.data = _default_store()
            return
        availability = raw.get("availability")
        days = raw.get("days")
        self.data = {
            "version": SCHEMA_VERSION,
            "availability": availability if isinstance(availability, dict) else {},
            "days": days if isinstance(days, dict) else {},
        }

    def save(self) -> bool:
        """Persist the full ledger. Does not drop old days or availability rows."""
        return atomic_save_json(self.path, self.data)

    def note_online(self, entity_id: str, when_iso: str, *, name: str, room_id: str, room_name: str, part: str) -> None:
        """Record that Home Assistant could read this entity. Never deletes prior rows."""
        eid = str(entity_id or "").strip()
        if not eid:
            return
        prev = self.data["availability"].get(eid)
        row = dict(prev) if isinstance(prev, dict) else {}
        row.update(
            {
                "name": name or row.get("name") or eid,
                "room_id": room_id or row.get("room_id") or "",
                "room_name": room_name or row.get("room_name") or "",
                "part": part or row.get("part") or "",
                "last_online": when_iso,
            }
        )
        self.data["availability"][eid] = row

    def last_online(self, entity_id: str) -> str | None:
        row = self.data["availability"].get(str(entity_id or "").strip())
        if not isinstance(row, dict):
            return None
        raw = row.get("last_online")
        return str(raw) if raw else None

    def upsert_energy_day(self, day: str, rooms: dict[str, Any], totals: dict[str, Any] | None = None) -> None:
        """Replace one day's energy snapshot. Leaves presence rows and other days alone."""
        if not day or len(day) < 10:
            return
        bucket = _day_bucket(self.data["days"], day[:10])
        bucket["rooms"] = rooms if isinstance(rooms, dict) else {}
        if isinstance(totals, dict):
            bucket["totals"] = totals

    def add_presence(
        self,
        day: str,
        person_id: str,
        person_name: str,
        tracker_id: str,
        tracker_name: str,
        state: str,
        *,
        is_home: bool,
        seconds: float,
    ) -> None:
        """Add observed seconds for one device tracker. Seconds only increase."""
        if seconds <= 0 or not day or not person_id or not tracker_id:
            return
        bucket = _day_bucket(self.data["days"], day[:10])
        persons = bucket["persons"]
        person = persons.get(person_id)
        if not isinstance(person, dict):
            person = {"name": person_name or person_id, "trackers": {}}
            persons[person_id] = person
        if person_name:
            person["name"] = person_name
        trackers = person.get("trackers")
        if not isinstance(trackers, dict):
            trackers = {}
            person["trackers"] = trackers
        tracker = trackers.get(tracker_id)
        if not isinstance(tracker, dict):
            tracker = {
                "name": tracker_name or tracker_id,
                "seconds_home": 0.0,
                "seconds_away": 0.0,
                "states": {},
            }
            trackers[tracker_id] = tracker
        if tracker_name:
            tracker["name"] = tracker_name
        secs = float(seconds)
        if is_home:
            tracker["seconds_home"] = float(tracker.get("seconds_home") or 0.0) + secs
        else:
            tracker["seconds_away"] = float(tracker.get("seconds_away") or 0.0) + secs
        states = tracker.get("states")
        if not isinstance(states, dict):
            states = {}
            tracker["states"] = states
        key = (state or "unknown").strip().lower() or "unknown"
        states[key] = float(states.get(key) or 0.0) + secs

    def month_days(self, month: str) -> dict[str, Any]:
        """Return YYYY-MM-DD → day bucket for one calendar month. Read-only copy."""
        prefix = f"{month}-"
        out: dict[str, Any] = {}
        for day, bucket in self.data.get("days", {}).items():
            if isinstance(day, str) and day.startswith(prefix) and isinstance(bucket, dict):
                out[day] = bucket
        return out
