"""Kidde and generic smoke-alarm mapping, plus outlet cutoff while an alarm is active."""
from __future__ import annotations

from typing import Any, Iterable

SMOKE_ROLES = (
    "smoke_alarm",
    "co_alarm",
    "hardwire_smoke",
    "co_ppm",
    "smoke_level",
    "hush",
    "test",
    "identifying",
    "smoke_hushed",
    "online",
    "battery",
)

_ALARM_ROLES = ("smoke_alarm", "co_alarm", "hardwire_smoke")

_SAFE_STATES = {
    "",
    "clear",
    "off",
    "ok",
    "none",
    "normal",
    "no_smoke",
    "no_co",
    "idle",
    "standby",
    "not_detected",
    "safe",
    "good",
    "unknown",
    "unavailable",
    "connected",
    "false",
}


def normalize_smoke_map(raw: Any) -> dict[str, str]:
    """Keep only known roles whose value looks like an entity id."""
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for role in SMOKE_ROLES:
        eid = str(raw.get(role) or "").strip()
        if "." in eid:
            out[role] = eid
    return out


def _norm_name(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().replace("_", " ").split())


def state_is_alarm(state: Any) -> bool:
    """True when a smoke or CO status entity is reporting an alarm."""
    raw = _norm_name(state).replace(" ", "_")
    if raw in _SAFE_STATES:
        return False
    if raw in {"on", "smoke", "alarm", "detected", "fire", "co", "carbon_monoxide", "emergency", "test"}:
        return True
    return "alarm" in raw or "smoke" in raw or raw == "co"


def classify_entities(rows: Iterable[dict[str, Any]]) -> dict[str, str]:
    """Map Kidde-style entity names onto the roles the card and cutoff use.

    First match wins. "Smoke Hushed" is not the Hush button, and "CO PPM" is
    not the CO alarm status.
    """
    found: dict[str, str] = {}

    def take(role: str, entity_id: str) -> None:
        if role not in found and entity_id:
            found[role] = entity_id

    for row in rows:
        eid = str(row.get("entity_id") or "").strip()
        if "." not in eid:
            continue
        name = _norm_name(row.get("name") or eid)
        domain = str(row.get("domain") or eid.split(".", 1)[0]).strip().lower()
        unit = _norm_name(row.get("unit"))
        if domain == "button" and "hush" in name and "hushed" not in name:
            take("hush", eid)
        elif domain == "button" and "test" in name:
            take("test", eid)
        elif domain in {"switch", "input_boolean"} and "identif" in name:
            take("identifying", eid)
        elif "co ppm" in name or (unit == "ppm" and "co" in name):
            take("co_ppm", eid)
        elif "smoke level" in name:
            take("smoke_level", eid)
        elif "smoke hushed" in name or name.endswith("hushed"):
            take("smoke_hushed", eid)
        elif "hardwire" in name and "smoke" in name:
            take("hardwire_smoke", eid)
        elif name in {"co alarm", "carbon monoxide alarm"} or (
            "co alarm" in name or "carbon monoxide alarm" in name
        ):
            take("co_alarm", eid)
        elif "smoke alarm" in name:
            take("smoke_alarm", eid)
        elif name in {"online", "status"} or name.endswith(" online"):
            take("online", eid)
        elif "battery" in name and "fault" not in name:
            take("battery", eid)
    return found


def alarm_is_active(entity_states: dict[str, str], mapped: dict[str, str]) -> bool:
    """True when smoke, CO, or hardwire smoke is in an alarm state."""
    for role in _ALARM_ROLES:
        eid = str(mapped.get(role) or "").strip()
        if eid and state_is_alarm(entity_states.get(eid, "")):
            return True
    return False


def cutoff_step(
    alarms: list[dict[str, Any]],
    on_now: set[str],
    held: dict[str, set[str]],
    restore: set[str],
) -> tuple[list[str], list[str], dict[str, set[str]], set[str]]:
    """Decide which switches to turn off, which to restore, and what to remember.

    A switch is turned off only if it is on when its alarm is active. It is
    turned back on only after every alarm that shut it off has cleared, and a
    failed restore is retried on the next pass.
    """
    new_held: dict[str, set[str]] = {}
    turn_off: list[str] = []
    for alarm in alarms:
        key = str(alarm.get("key") or "")
        if not key:
            continue
        previous = set(held.get(key) or ())
        if not alarm.get("active"):
            new_held[key] = set()
            continue
        nxt: set[str] = set()
        for sw in alarm.get("switches") or []:
            eid = str(sw or "").strip()
            if "." not in eid:
                continue
            if eid in on_now:
                turn_off.append(eid)
                nxt.add(eid)
            elif eid in previous:
                nxt.add(eid)
        new_held[key] = nxt

    held_now: set[str] = set()
    for switches in new_held.values():
        held_now |= switches
    old_held: set[str] = set()
    for switches in held.values():
        old_held |= set(switches or ())
    candidates = (old_held | set(restore)) - held_now
    turn_on = [sw for sw in candidates if sw not in on_now]
    new_restore = set(turn_on)
    return list(dict.fromkeys(turn_off)), turn_on, new_held, new_restore


def _rows_for_device(hass: Any, entity_id: str | None, device_id: str | None) -> tuple[str | None, list[dict[str, Any]]]:
    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    resolved = str(device_id or "").strip() or None
    if not resolved and entity_id:
        entry = registry.async_get(str(entity_id).strip())
        if entry is None:
            return None, []
        resolved = entry.device_id
    if not resolved:
        return None, []
    rows: list[dict[str, Any]] = []
    for entry in er.async_entries_for_device(registry, resolved, include_disabled_entities=False):
        state = hass.states.get(entry.entity_id)
        name = entry.name or entry.original_name or (state.name if state else "") or entry.entity_id
        attrs = state.attributes if state else {}
        rows.append(
            {
                "entity_id": entry.entity_id,
                "name": name,
                "domain": entry.entity_id.split(".", 1)[0],
                "unit": attrs.get("unit_of_measurement") or "",
            }
        )
    return resolved, rows


def resolve_smoke_device(hass: Any, entity_id: str | None = None, device_id: str | None = None) -> dict[str, Any]:
    """Classify every entity on the Home Assistant device that owns the anchor."""
    resolved, rows = _rows_for_device(hass, entity_id, device_id)
    mapped = classify_entities(rows)
    found = [{"role": role, "entity_id": eid} for role, eid in mapped.items()]
    return {"device_id": resolved, "entities": mapped, "found": found}


def live_smoke_map(hass: Any, outlet: dict[str, Any]) -> dict[str, str]:
    """Prefer a fresh Kidde device lookup, then the map saved with the card."""
    saved = normalize_smoke_map(outlet.get("smoke_map"))
    brand = str(outlet.get("smoke_brand") or "kidde").strip().lower()
    if brand != "kidde":
        return saved
    try:
        resolved = resolve_smoke_device(
            hass,
            outlet.get("smoke_anchor"),
            outlet.get("smoke_device_id"),
        )
    except Exception:
        return saved
    live = normalize_smoke_map(resolved.get("entities"))
    if not live:
        return saved
    merged = dict(saved)
    merged.update(live)
    return merged


async def async_enforce_smoke_alarms(
    hass: Any,
    rooms: list[dict[str, Any]],
    held: dict[str, set[str]],
    restore: set[str],
    turn_switch,
) -> None:
    """Turn selected outlets off while a smoke or CO alarm is active, then restore them."""
    alarms: list[dict[str, Any]] = []
    watched: set[str] = set()
    for room in rooms or []:
        room_id = str(room.get("id") or room.get("name") or "").strip()
        for outlet in room.get("outlets") or []:
            if not isinstance(outlet, dict) or outlet.get("type") != "smoke_alarm":
                continue
            mapped = live_smoke_map(hass, outlet)
            switches = [
                str(eid).strip()
                for eid in (outlet.get("alarm_cut_switches") or [])
                if str(eid).strip().startswith(("switch.", "fan."))
            ]
            states = {eid: (hass.states.get(eid).state if hass.states.get(eid) else "") for eid in mapped.values()}
            alarms.append(
                {
                    "key": f"{room_id}|{outlet.get('name') or 'smoke'}",
                    "active": alarm_is_active(states, mapped),
                    "switches": switches,
                }
            )
            watched.update(switches)

    on_now = set()
    for eid in watched | set(restore) | {sw for group in held.values() for sw in group}:
        state = hass.states.get(eid)
        if state is not None and str(state.state or "").lower() == "on":
            on_now.add(eid)

    turn_off, turn_on, new_held, new_restore = cutoff_step(alarms, on_now, held, restore)
    for eid in turn_off:
        await turn_switch(eid, False)
    for eid in turn_on:
        await turn_switch(eid, True)
    held.clear()
    held.update(new_held)
    restore.clear()
    restore.update(new_restore)
