"""History that routine cleanup must not delete.

Daily energy, person/device-tracker presence, and last-online timestamps live
here. Retention jobs that trim intraday charts, the 45-day totals file, and
the event archive do not touch this store.
"""
from __future__ import annotations

import logging
from datetime import datetime
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
        "door",
        "window",
        "oil_diffuser",
    }
)


def _default_store() -> dict[str, Any]:
    return {"version": SCHEMA_VERSION, "availability": {}, "days": {}, "periods": {}, "connectivity": []}


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


def appliance_type_catalog(rooms: list | None) -> dict[tuple[str, str], str]:
    """Map (room id, device name) to the configured appliance type."""
    catalog: dict[tuple[str, str], str] = {}
    for room in rooms or []:
        if not isinstance(room, dict):
            continue
        rid = room_id_of(room)
        for outlet in room.get("outlets") or []:
            if not isinstance(outlet, dict):
                continue
            name = str(outlet.get("name") or "").strip().lower()
            if not name:
                continue
            catalog[(rid, name)] = str(outlet.get("type") or "outlet").strip().lower() or "outlet"
    return catalog


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
        add(outlet.get("switch_entity"), "Switch")
        if outlet.get("power_source") == "sensor":
            add(outlet.get("power_sensor_entity"), "Power")
    elif otype in ("vent", "wall_heater"):
        add(outlet.get("switch_entity"), "Switch")
        if outlet.get("power_source") == "sensor":
            add(outlet.get("power_sensor_entity"), "Power")
    elif otype == "oil_diffuser":
        from .diffuser_automation import control_switch_entity

        control = control_switch_entity(outlet)
        add(control, "Diffuser")
        add(outlet.get("plug1_entity"), "Power")
        plug_switch = str(outlet.get("plug1_switch") or "").strip()
        if plug_switch and plug_switch != (control or ""):
            add(plug_switch, "Plug")
    elif otype in ("door", "window"):
        add(outlet.get("contact_sensor"), "Open/closed")
    elif otype in ("single_outlet", "minisplit", "stove", "microwave", "fridge"):
        add(outlet.get("plug1_switch"), "Switch")
        if outlet.get("power_source") == "sensor":
            add(outlet.get("power_sensor_entity"), "Power")
        else:
            add(outlet.get("plug1_entity"), "Power")

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


# A wifi device that is really offline stays unavailable. Home Assistant also
# marks entities unavailable for a short time while it starts, and may restore
# the last on/off state before that. Wait out that flap before logging.
HOLD_SECONDS = 180
# A reconnect and a new disconnect this close together are the same outage.
STITCH_SECONDS = 300


def _parse_ts(text: Any) -> datetime | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _device_key(row: dict[str, Any]) -> tuple[str, str]:
    room = str(row.get("room_name") or row.get("room_id") or "").strip().lower()
    name = str(row.get("name") or row.get("entity_id") or "device").strip().lower()
    return room, name


def collapse_connectivity_events(
    events: list[dict[str, Any]] | None,
    stitch_seconds: int = STITCH_SECONDS,
) -> list[dict[str, Any]]:
    """One row per device outage.

    Extra disconnects while the device is already offline are dropped. A reconnect
    that is followed by another disconnect within stitch_seconds is treated as
    Home Assistant starting, not as the device coming back.
    """
    rows = [row for row in (events or []) if isinstance(row, dict)]
    rows.sort(key=lambda row: str(row.get("at") or ""))
    active: dict[tuple[str, str], dict[str, Any]] = {}
    finished: list[dict[str, Any]] = []

    def flush_closed(key: tuple[str, str], now: datetime | None) -> None:
        episode = active.get(key)
        if not episode or not episode.get("online_at"):
            return
        ended = _parse_ts(episode.get("online_at"))
        if ended is None or now is None:
            return
        try:
            gap = (now - ended).total_seconds()
        except TypeError:
            return
        if gap > stitch_seconds:
            finished.append(episode)
            active.pop(key, None)

    for row in rows:
        key = _device_key(row)
        now = _parse_ts(row.get("at"))
        flush_closed(key, now)
        kind = str(row.get("event") or "")
        part = str(row.get("part") or "").strip()
        episode = active.get(key)
        if kind == "disconnected":
            if episode and not episode.get("online_at"):
                if part:
                    episode["offline_parts"].add(part)
                    episode["parts"].add(part)
                continue
            if episode and episode.get("online_at"):
                episode["online_at"] = ""
                if part:
                    episode["offline_parts"].add(part)
                    episode["parts"].add(part)
                elif not episode["offline_parts"]:
                    episode["offline_parts"].add("")
                continue
            active[key] = {
                "name": str(row.get("name") or ""),
                "room_name": str(row.get("room_name") or ""),
                "room_id": str(row.get("room_id") or ""),
                "entity_id": str(row.get("entity_id") or ""),
                "appliance_type": str(row.get("appliance_type") or "").strip().lower(),
                "offline_at": str(row.get("at") or ""),
                "online_at": "",
                "parts": {part} if part else set(),
                "offline_parts": {part} if part else {""},
            }
            continue
        if kind != "reconnected" or episode is None or episode.get("online_at"):
            continue
        if part and episode["offline_parts"]:
            episode["offline_parts"].discard(part)
            if episode["offline_parts"]:
                continue
        elif episode["offline_parts"] == {""}:
            episode["offline_parts"].clear()
        episode["online_at"] = str(row.get("at") or "")
        if not episode.get("appliance_type"):
            episode["appliance_type"] = str(row.get("appliance_type") or "").strip().lower()

    finished.extend(active.values())
    finished.sort(key=lambda episode: str(episode.get("offline_at") or ""))
    return finished


def _episodes_to_events(episodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for episode in episodes:
        parts = sorted(part for part in episode.get("parts") or set() if part)
        base = {
            "entity_id": episode.get("entity_id") or "",
            "name": episode.get("name") or "",
            "room_id": episode.get("room_id") or "",
            "room_name": episode.get("room_name") or "",
            "part": ", ".join(parts),
            "appliance_type": episode.get("appliance_type") or "",
        }
        out.append({**base, "at": episode.get("offline_at") or "", "event": "disconnected"})
        if episode.get("online_at"):
            out.append({**base, "at": episode.get("online_at") or "", "event": "reconnected"})
    return out


def _compact_connectivity(events: list[Any]) -> list[dict[str, Any]]:
    raw = [row for row in events if isinstance(row, dict)]
    compacted = _episodes_to_events(collapse_connectivity_events(raw))
    if len(compacted) < len(raw):
        return compacted
    return raw


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
        periods = raw.get("periods")
        connectivity = raw.get("connectivity")
        if not isinstance(availability, dict):
            availability = {}
        for row in availability.values():
            if isinstance(row, dict):
                row.pop("pending_status", None)
                row.pop("pending_since", None)
        if not isinstance(connectivity, list):
            connectivity = []
        self.data = {
            "version": SCHEMA_VERSION,
            "availability": availability,
            "days": days if isinstance(days, dict) else {},
            "periods": periods if isinstance(periods, dict) else {},
            "connectivity": _compact_connectivity(connectivity),
        }

    def note_period(self, start: str, end: str, when_iso: str) -> bool:
        """Remember a billing period seen on the billing sensors. Returns True when new."""
        a = str(start or "").strip()
        b = str(end or "").strip()
        if len(a) != 10 or len(b) != 10 or a > b:
            return False
        key = f"{a}_{b}"
        periods = self.data.setdefault("periods", {})
        if key in periods:
            return False
        periods[key] = {"start": a, "end": b, "first_seen": when_iso}
        return True

    def periods(self) -> list[dict[str, str]]:
        """All billing periods ever seen, newest first."""
        rows = []
        for key, row in (self.data.get("periods") or {}).items():
            if not isinstance(row, dict):
                continue
            start = str(row.get("start") or "")
            end = str(row.get("end") or "")
            if start and end:
                rows.append({"key": str(key), "start": start, "end": end})
        rows.sort(key=lambda r: (r["start"], r["end"]), reverse=True)
        return rows

    def range_days(self, start: str, end: str) -> dict[str, Any]:
        """Return YYYY-MM-DD → day bucket for an inclusive date range. Read-only copy."""
        a = str(start or "").strip()[:10]
        b = str(end or "").strip()[:10]
        out: dict[str, Any] = {}
        if not a or not b or a > b:
            return out
        for day, bucket in self.data.get("days", {}).items():
            if isinstance(day, str) and a <= day[:10] <= b and isinstance(bucket, dict):
                out[day] = bucket
        return out

    def save(self) -> bool:
        """Persist the full ledger. Does not drop old days or availability rows."""
        return atomic_save_json(self.path, self.data)

    def note_online(self, entity_id: str, when_iso: str, *, name: str, room_id: str, room_name: str, part: str) -> None:
        """Record that Home Assistant could read this entity. Never deletes prior rows."""
        self.note_observed(
            entity_id,
            when_iso,
            online=True,
            name=name,
            room_id=room_id,
            room_name=room_name,
            part=part,
        )

    def note_observed(
        self,
        entity_id: str,
        when_iso: str,
        *,
        online: bool,
        name: str,
        room_id: str,
        room_name: str,
        part: str,
        appliance_type: str = "",
    ) -> bool:
        """Remember online or offline. Log a row only after the new status holds.

        Home Assistant startup often looks like a disconnect, then a reconnect, even
        when the device never came back. A new status must stay in place for
        HOLD_SECONDS before it is stored. The first confirmed online reading does
        not write an event. Returns True when a log row was added.
        """
        eid = str(entity_id or "").strip()
        if not eid:
            return False
        availability = self.data.setdefault("availability", {})
        prev = availability.get(eid)
        row = dict(prev) if isinstance(prev, dict) else {}
        previous = str(row.get("status") or "")
        status = "online" if online else "offline"
        row.update(
            {
                "name": name or row.get("name") or eid,
                "room_id": room_id or row.get("room_id") or "",
                "room_name": room_name or row.get("room_name") or "",
                "part": part or row.get("part") or "",
                "appliance_type": str(appliance_type or row.get("appliance_type") or "").strip().lower(),
            }
        )
        if previous == status:
            row.pop("pending_status", None)
            row.pop("pending_since", None)
            if online:
                row["last_online"] = when_iso
            availability[eid] = row
            return False

        pending = str(row.get("pending_status") or "")
        if pending != status:
            row["pending_status"] = status
            row["pending_since"] = when_iso
            availability[eid] = row
            return False

        started = _parse_ts(row.get("pending_since"))
        seen = _parse_ts(when_iso)
        try:
            held = started is not None and seen is not None and (seen - started).total_seconds() >= HOLD_SECONDS
        except TypeError:
            held = False
        if not held:
            availability[eid] = row
            return False

        event_at = str(row.get("pending_since") or when_iso)
        row.pop("pending_status", None)
        row.pop("pending_since", None)
        row["status"] = status
        row["status_at"] = event_at
        if online:
            row["last_online"] = when_iso
        availability[eid] = row
        if not previous and online:
            return False
        event = "reconnected" if online else "disconnected"
        log = self.data.setdefault("connectivity", [])
        if not isinstance(log, list):
            log = []
            self.data["connectivity"] = log
        log.append(
            {
                "at": event_at,
                "entity_id": eid,
                "name": row["name"],
                "room_id": row["room_id"],
                "room_name": row["room_name"],
                "part": row["part"],
                "appliance_type": row.get("appliance_type") or "",
                "event": event,
            }
        )
        return True

    def events_between(self, start: str, end: str) -> list[dict[str, Any]]:
        """Connectivity events whose timestamp falls on an inclusive YYYY-MM-DD range."""
        a = str(start or "").strip()[:10]
        b = str(end or "").strip()[:10]
        out: list[dict[str, Any]] = []
        if not a or not b or a > b:
            return out
        for row in self.data.get("connectivity") or []:
            if not isinstance(row, dict):
                continue
            day = str(row.get("at") or "")[:10]
            if a <= day <= b:
                out.append(dict(row))
        out.sort(key=lambda row: str(row.get("at") or ""))
        return out

    def stamp_appliance_types(self, catalog: dict[tuple[str, str], str]) -> bool:
        """Fill a missing appliance type from the current device setup. Returns True if anything changed."""
        changed = False

        def apply(row: dict[str, Any], field: str, room_id: str | None = None) -> None:
            nonlocal changed
            if not isinstance(row, dict) or str(row.get(field) or "").strip():
                return
            name = str(row.get("name") or "").strip().lower()
            rid = str(room_id if room_id is not None else row.get("room_id") or "")
            otype = catalog.get((rid, name))
            if not otype:
                return
            row[field] = otype
            changed = True

        for bucket in (self.data.get("days") or {}).values():
            rooms = bucket.get("rooms") if isinstance(bucket, dict) else None
            if not isinstance(rooms, dict):
                continue
            for room_id, room in rooms.items():
                if not isinstance(room, dict):
                    continue
                for device in room.get("devices") or []:
                    apply(device, "type", str(room_id))
        for row in self.data.get("connectivity") or []:
            apply(row, "appliance_type")
        availability = self.data.get("availability")
        if isinstance(availability, dict):
            for row in availability.values():
                apply(row, "appliance_type")
        return changed

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
