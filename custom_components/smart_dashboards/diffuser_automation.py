"""Oil diffuser control and spray schedules.

The Airversa Scenta integration (ha-airversa-diffuser-int) exposes each
diffuser as one ``switch`` entity. Its BLE frames are on (``2d13``) and off
(``2d12``) only, so mist frequency is produced here by turning that switch
on and off. Regular (ultrasonic / plug) diffusers stay on for the whole
schedule window.
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Awaitable, Callable

MODES = ("airversa", "regular")
_LEGACY_REGULAR = frozenset({"generic", "water", "regular"})

# Lowest → highest. Spray seconds, rest seconds.
AIRVERSA_INTENSITY_STEPS: tuple[tuple[int, int], ...] = (
    (15, 300),
    (72, 360),
    (129, 420),
    (186, 480),
    (243, 540),
    (300, 600),
)
AIRVERSA_INTENSITY_MAX = len(AIRVERSA_INTENSITY_STEPS) - 1

# on/off limits are (min, max, default, unit).
MODE_SPECS: dict[str, dict[str, Any]] = {
    "airversa": {
        "patterns": ("intermittent",),
        "default_pattern": "intermittent",
        "on": (15, 300, 15, "seconds"),
        "off": (300, 600, 300, "seconds"),
    },
    "regular": {
        "patterns": ("continuous",),
        "default_pattern": "continuous",
        "on": (1, 240, 30, "minutes"),
        "off": (1, 240, 30, "minutes"),
    },
}


def normalize_mode(value: Any) -> str:
    mode = str(value or "airversa").strip().lower()
    if mode in _LEGACY_REGULAR:
        return "regular"
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


def airversa_step(intensity: Any) -> tuple[int, int, int]:
    """Return ``(index, spray_sec, rest_sec)`` snapped onto the intensity scale."""
    idx = _clamp_int(intensity, 0, AIRVERSA_INTENSITY_MAX, 0)
    on_sec, off_sec = AIRVERSA_INTENSITY_STEPS[idx]
    return idx, on_sec, off_sec


def nearest_airversa_intensity(on_amount: Any, off_amount: Any) -> int:
    try:
        on_sec = int(on_amount)
        off_sec = int(off_amount)
    except (TypeError, ValueError):
        return 0
    best = 0
    best_d: int | None = None
    for idx, (step_on, step_off) in enumerate(AIRVERSA_INTENSITY_STEPS):
        distance = abs(step_on - on_sec) + abs(step_off - off_sec)
        if best_d is None or distance < best_d:
            best_d = distance
            best = idx
    return best


def normalize_schedule(outlet: dict | None) -> dict[str, Any]:
    """Clamp a diffuser schedule to the limits of its current mode."""
    outlet = outlet or {}
    mode = normalize_mode(outlet.get("diffuser_mode"))
    spec = MODE_SPECS[mode]
    raw = schedule_from(outlet)
    if mode == "airversa":
        if raw.get("intensity") is None:
            intensity = nearest_airversa_intensity(raw.get("on_amount"), raw.get("off_amount"))
        else:
            intensity, _on_sec, _off_sec = airversa_step(raw.get("intensity"))
        intensity, on_sec, off_sec = airversa_step(intensity)
        return {
            "enabled": bool(raw.get("enabled")),
            "start": _hhmm(raw.get("start"), "08:00"),
            "end": _hhmm(raw.get("end"), "22:00"),
            "pattern": "intermittent",
            "intensity": intensity,
            "on_amount": on_sec,
            "off_amount": off_sec,
        }

    return {
        "enabled": bool(raw.get("enabled")),
        "start": _hhmm(raw.get("start"), "08:00"),
        "end": _hhmm(raw.get("end"), "22:00"),
        "pattern": spec["default_pattern"],
        "intensity": 0,
        "on_amount": spec["on"][2],
        "off_amount": spec["off"][2],
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


def seconds_until_window_start(now: datetime, start: str) -> int:
    current = now.hour * 60 + now.minute
    start_m = _minutes(start)
    if start_m > current:
        return (start_m - current) * 60 - now.second
    if start_m == current:
        return max(0, 60 - now.second)
    return ((24 * 60 - current) + start_m) * 60 - now.second


def next_spray_seconds(
    *,
    schedule: dict[str, Any],
    runtime: dict | None,
    now: datetime,
    mode: str,
) -> int | None:
    """Seconds until the next spray, or ``None`` when nothing is scheduled."""
    if not schedule.get("enabled"):
        return None
    resolved = normalize_mode(mode)
    if not in_active_window(now, schedule["start"], schedule["end"]):
        return max(0, seconds_until_window_start(now, schedule["start"]))
    if resolved == "regular" or schedule.get("pattern") == "continuous":
        return None
    slot = runtime if isinstance(runtime, dict) else {}
    on_sec, off_sec = cycle_seconds(resolved, schedule)
    mono = time.monotonic()
    if slot.get("manual"):
        manual_until = float(slot.get("manual_until") or 0)
        if manual_until > mono:
            return int(max(0, manual_until - mono) + off_sec)
    until = float(slot.get("until") or 0)
    remain = max(0, until - mono) if until else 0
    phase = slot.get("phase")
    if phase == "off":
        return int(remain)
    if phase == "on":
        return int(remain + off_sec)
    return 0


def control_switch_entity(outlet: dict | None) -> str | None:
    """Switch the schedule and the on/off menu should call."""
    if not isinstance(outlet, dict):
        return None
    mode = normalize_mode(outlet.get("diffuser_mode"))
    dedicated = str(outlet.get("diffuser_switch") or "").strip()
    plug = str(outlet.get("plug1_switch") or "").strip()
    if mode == "regular":
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


def manual_spray_seconds(outlet: dict | None) -> int:
    """Duration for a one-shot manual spray.

    Uses the saved Airversa intensity when a schedule has been configured;
    otherwise 5 seconds. Regular units have no spray pulse, so they also
    default to 5 seconds.
    """
    raw = schedule_from(outlet)
    mode = normalize_mode((outlet or {}).get("diffuser_mode"))
    if mode != "airversa" or not raw:
        return 5
    schedule = normalize_schedule(outlet)
    on_sec, _off_sec = cycle_seconds(mode, schedule)
    return max(1, on_sec)


def public_diffuser_state(
    is_on: bool,
    phase: str | None,
    outlet: dict | None,
    runtime: dict | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    schedule = normalize_schedule(outlet)
    mode = normalize_mode((outlet or {}).get("diffuser_mode"))
    next_sec = next_spray_seconds(
        schedule=schedule,
        runtime=runtime,
        now=now or datetime.now(),
        mode=mode,
    )
    return {
        "switch_state": bool(is_on),
        "diffuser_phase": phase or ("on" if is_on else "off"),
        "diffuser_mode": mode,
        "diffuser_pattern": schedule["pattern"],
        "diffuser_enabled": schedule["enabled"],
        "diffuser_next_spray_sec": next_sec,
    }


async def async_start_manual_spray(
    *,
    runtime_map: dict[str, dict],
    status_map: dict[str, str],
    key: str,
    outlet: dict,
    set_switch: Callable[[str, bool], Awaitable[None]],
    duration_sec: int | None = None,
) -> int:
    """Turn the diffuser on for a timed burst, then let the tick turn it off."""
    entity = control_switch_entity(outlet)
    if not entity:
        raise ValueError("unconfigured")
    duration = int(duration_sec) if duration_sec is not None else manual_spray_seconds(outlet)
    duration = max(1, min(duration, 300))
    await set_switch(entity, True)
    slot = runtime_map.setdefault(key, {})
    mono = time.monotonic()
    slot["manual"] = True
    slot["manual_until"] = mono + duration
    slot["last"] = True
    slot["grace_until"] = mono + 4
    status_map[key] = "manual"
    return duration


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
    mono = time.monotonic()

    if slot.get("manual"):
        timed_until = float(slot.get("manual_until") or 0)
        if timed_until:
            if mono < timed_until:
                status_map[key] = "manual"
                return
            if live:
                await set_switch(entity, False)
                slot["grace_until"] = mono + 4
                slot["last"] = False
                live = False
            slot["manual"] = False
            slot.pop("manual_until", None)
        else:
            status_map[key] = "manual"
            return

    if not schedule["enabled"]:
        slot.clear()
        status_map[key] = "on" if live else "off"
        return
    if not in_active_window(now, schedule["start"], schedule["end"]):
        status_map[key] = "idle"
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
        slot.pop("manual_until", None)
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
        slot.pop("manual_until", None)
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
