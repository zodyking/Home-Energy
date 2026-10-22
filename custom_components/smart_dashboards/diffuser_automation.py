"""Oil diffuser control and spray schedules.

The Airversa Scenta integration (ha-airversa-diffuser-int) exposes each
diffuser as one ``switch`` entity. Its BLE frames are on (``2d13``) and off
(``2d12``) only, so mist frequency is produced here by turning that switch
on and off. Generic diffusers use the power plug the same way, on a slower
cycle. Water diffusers use a short spray and a longer pause.
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Awaitable, Callable

MODES = ("airversa", "generic", "water")

# on/off limits are (min, max, default, unit).
MODE_SPECS: dict[str, dict[str, Any]] = {
    "airversa": {
        "patterns": ("continuous", "intermittent"),
        "default_pattern": "intermittent",
        "on": (1, 180, 10, "seconds"),
        "off": (5, 600, 20, "seconds"),
    },
    "generic": {
        "patterns": ("continuous", "cycle"),
        "default_pattern": "cycle",
        "on": (1, 240, 30, "minutes"),
        "off": (1, 240, 30, "minutes"),
    },
    "water": {
        "patterns": ("continuous", "burst"),
        "default_pattern": "burst",
        "on": (1, 120, 8, "seconds"),
        "off": (1, 180, 10, "minutes"),
    },
}


def normalize_mode(value: Any) -> str:
    mode = str(value or "airversa").strip().lower()
    return mode if mode in MODE_SPECS else "airversa"


def _clamp_int(value: Any, low: int, high: int, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def _hhmm(value: Any, fallback: str) -> str:
    text = str(value or "").strip()
    parts = text.split(":")
    if len(parts) < 2:
        return fallback
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError:
        return fallback
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return fallback
    return f"{hour:02d}:{minute:02d}"


def _minutes(hhmm: str) -> int:
    hour, minute = hhmm.split(":")
    return int(hour) * 60 + int(minute)


def schedule_from(outlet: dict | None) -> dict[str, Any]:
    raw = {}
    if isinstance(outlet, dict):
        stored = outlet.get("diffuser_schedule")
        if isinstance(stored, dict):
            raw = stored
    return raw


def normalize_schedule(outlet: dict | None) -> dict[str, Any]:
    """Clamp a diffuser schedule to the limits of its current mode."""
    outlet = outlet or {}
    mode = normalize_mode(outlet.get("diffuser_mode"))
    spec = MODE_SPECS[mode]
    raw = schedule_from(outlet)
    pattern = str(raw.get("pattern") or spec["default_pattern"]).strip().lower()
    if pattern not in spec["patterns"]:
        pattern = spec["default_pattern"]
    on_min, on_max, on_default, _on_unit = spec["on"]
    off_min, off_max, off_default, _off_unit = spec["off"]
    return {
        "enabled": bool(raw.get("enabled")),
        "start": _hhmm(raw.get("start"), "08:00"),
        "end": _hhmm(raw.get("end"), "22:00"),
        "pattern": pattern,
        "on_amount": _clamp_int(raw.get("on_amount"), on_min, on_max, on_default),
        "off_amount": _clamp_int(raw.get("off_amount"), off_min, off_max, off_default),
    }


def cycle_seconds(mode: str, schedule: dict[str, Any]) -> tuple[int, int]:
    spec = MODE_SPECS[normalize_mode(mode)]
    on_amount = int(schedule["on_amount"])
    off_amount = int(schedule["off_amount"])
    on_sec = on_amount * (60 if spec["on"][3] == "minutes" else 1)
    off_sec = off_amount * (60 if spec["off"][3] == "minutes" else 1)
    return max(1, on_sec), max(1, off_sec)


def in_active_window(now: datetime, start: str, end: str) -> bool:
    current = now.hour * 60 + now.minute
    start_m = _minutes(start)
    end_m = _minutes(end)
    if start_m == end_m:
        return True
    if start_m < end_m:
        return start_m <= current < end_m
    return current >= start_m or current < end_m


def control_switch_entity(outlet: dict | None) -> str | None:
    """Switch the schedule and the on/off menu should call."""
    if not isinstance(outlet, dict):
        return None
    mode = normalize_mode(outlet.get("diffuser_mode"))
    dedicated = str(outlet.get("diffuser_switch") or "").strip()
    plug = str(outlet.get("plug1_switch") or "").strip()
    if mode == "generic":
        return plug if plug.startswith("switch.") else None
    if mode == "water":
        if dedicated.startswith("switch."):
            return dedicated
        return plug if plug.startswith("switch.") else None
    return dedicated if dedicated.startswith("switch.") else None


def diffuser_runtime_key(room_id: str, outlet_index: int) -> str:
    return f"{room_id}|{int(outlet_index)}"


def claimed_non_diffuser_power_entities(rooms: list | None) -> set[str]:
    """Power entities already owned by a non-diffuser device.

    A diffuser often sits on a plug that is already a monitored outlet.
    Those watts must stay on that outlet so room totals are not doubled.
    """
    claimed: set[str] = set()
    for room in rooms or []:
        if not isinstance(room, dict):
            continue
        for outlet in room.get("outlets") or []:
            if not isinstance(outlet, dict):
                continue
            if str(outlet.get("type") or "") == "oil_diffuser":
                continue
            for key in ("plug1_entity", "plug2_entity", "power_sensor_entity"):
                entity_id = str(outlet.get(key) or "").strip()
                if entity_id:
                    claimed.add(entity_id)
    return claimed


def diffuser_power_already_counted(outlet: dict, claimed: set[str]) -> bool:
    """True when this diffuser must not add its plug into a room energy total."""
    if str(outlet.get("type") or "") != "oil_diffuser":
        return False
    entity_id = str(outlet.get("plug1_entity") or "").strip()
    if not entity_id:
        return True
    return entity_id in claimed


def public_diffuser_state(
    is_on: bool,
    phase: str | None,
    outlet: dict | None,
) -> dict[str, Any]:
    schedule = normalize_schedule(outlet)
    return {
        "switch_state": bool(is_on),
        "diffuser_phase": phase or ("on" if is_on else "off"),
        "diffuser_mode": normalize_mode((outlet or {}).get("diffuser_mode")),
        "diffuser_pattern": schedule["pattern"],
        "diffuser_enabled": schedule["enabled"],
    }


async def async_tick_diffuser(
    *,
    entity_state: str | None,
    runtime_map: dict[str, dict],
    status_map: dict[str, str],
    key: str,
    outlet: dict,
    now: datetime,
    set_switch: Callable[[str, bool], Awaitable[None]],
) -> None:
    """Advance one diffuser schedule. ``entity_state`` is the live switch state."""
    entity = control_switch_entity(outlet)
    slot = runtime_map.setdefault(key, {})
    if not entity:
        status_map[key] = "unconfigured"
        return
    raw = str(entity_state or "").strip().lower()
    if raw in ("", "unavailable", "unknown", "none"):
        status_map[key] = "offline"
        return
    live = raw == "on"
    schedule = normalize_schedule(outlet)
    if not schedule["enabled"]:
        slot.clear()
        status_map[key] = "on" if live else "off"
        return
    if not in_active_window(now, schedule["start"], schedule["end"]):
        status_map[key] = "idle"
        mono = time.monotonic()
        if not live:
            slot.clear()
            return
        if float(slot.get("grace_until") or 0) > mono:
            return
        await set_switch(entity, False)
        slot["grace_until"] = mono + 4
        slot["last"] = False
        slot["manual"] = False
        slot.pop("phase", None)
        return

    mono = time.monotonic()
    if slot.get("manual"):
        status_map[key] = "manual"
        return
    grace_until = float(slot.get("grace_until") or 0)
    if grace_until > mono:
        if live == slot.get("last"):
            slot["grace_until"] = 0
        else:
            status_map[key] = "spraying" if slot.get("last") else "paused"
            return
    elif slot.get("last") is not None and live != slot.get("last"):
        slot["manual"] = True
        status_map[key] = "manual"
        return

    mode = normalize_mode(outlet.get("diffuser_mode"))
    if schedule["pattern"] == "continuous":
        desired = True
        phase_name = "spraying"
    else:
        on_sec, off_sec = cycle_seconds(mode, schedule)
        if mono >= float(slot.get("until") or 0):
            if slot.get("phase") is None:
                phase = "on"
            else:
                phase = "off" if slot.get("phase") == "on" else "on"
            slot["phase"] = phase
            slot["until"] = mono + (on_sec if phase == "on" else off_sec)
        desired = slot.get("phase") == "on"
        phase_name = "spraying" if desired else "paused"

    if live != desired:
        await set_switch(entity, desired)
        slot["grace_until"] = mono + 4
    slot["last"] = desired
    status_map[key] = phase_name
