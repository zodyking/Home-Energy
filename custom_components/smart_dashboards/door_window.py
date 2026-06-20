"""Door/window/lock/presence automation helpers for Smart Dashboards.

Centralizes helpers that were previously duplicated inline in
``energy_monitor.py`` and ``websocket.py``:

* :func:`contact_is_open` — single source of truth for the open-state check
  (audit BUG 8: the heater-block check, the contact handler, the reminder
  loop, and the frontend each had their own copy, and the heater-block copy
  only accepted ``"on"`` while the contact handler accepted both ``"on"`` and
  ``"open"``).
* :func:`find_door_window_outlet_by_field` — generic O(n) outlet lookup by
  field name (contact_sensor / lock_entity / presence_sensor), replacing the
  three near-identical ``_find_door_window_outlet_by_*`` scans.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

# Canonical open-state values for HA binary_sensor contact / door / window
# entities. HA core uses ``on``/``off``; some MQTT/Zigbee mappings expose the
# legacy ``open``/``closed`` strings. Both are accepted everywhere.
_OPEN_STATES = frozenset(("on", "open"))


def contact_is_open(state: str | None) -> bool:
    """True if a contact/door/window sensor state means "open".

    Use this everywhere instead of ad-hoc ``== "on"`` / ``== "open"`` checks
    (audit BUG 8).
    """
    if not state:
        return False
    return str(state).strip().lower() in _OPEN_STATES


def find_door_window_outlet_by_field(
    rooms: list[dict], field: str, entity_id: str
) -> tuple[dict, dict, str] | None:
    """Find ``(outlet, room, device_type)`` where ``outlet[field] == entity_id``.

    Replaces the three near-identical ``_find_door_window_outlet_by_contact_sensor``
    / ``_by_lock_entity`` / ``_by_presence_sensor`` scans. The ``device_type``
    returned is the outlet's ``type`` ("door" or "window").
    """
    if not entity_id:
        return None
    for room in rooms or []:
        for outlet in room.get("outlets", []):
            if outlet.get("type") not in ("door", "window"):
                continue
            if outlet.get(field) == entity_id:
                return outlet, room, outlet.get("type")
    return None


def announce_door_event_key(outlet: dict, room: dict) -> str:
    """Stable key for door/window event tracking (mirrors ``_door_window_key``)."""
    room_id = room.get("id", room.get("name", "room").lower().replace(" ", "_"))
    outlet_name = (outlet.get("name") or "device").lower().replace(" ", "_")
    return f"{room_id}_{outlet_name}"
