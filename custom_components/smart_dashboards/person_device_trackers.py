"""Resolve device_tracker.* entity IDs linked to a person (Person integration + state fallback)."""
from __future__ import annotations

from homeassistant.core import HomeAssistant


def get_person_device_tracker_entity_ids(
    hass: HomeAssistant, person_entity_id: str
) -> list[str]:
    """Return device_tracker.* linked to a person.

    Uses homeassistant.components.person.entities_in_person when available (same as HA UI),
    then falls back to person state attributes device_trackers.
    """
    try:
        from homeassistant.components.person import entities_in_person
    except ImportError:
        entities_in_person = None

    if entities_in_person is not None:
        linked = entities_in_person(hass, person_entity_id)
        if linked:
            out = [
                str(t).strip()
                for t in linked
                if str(t).strip().startswith("device_tracker.")
            ]
            if out:
                return out

    ps = hass.states.get(person_entity_id)
    if not ps:
        return []
    raw = ps.attributes.get("device_trackers")
    if raw is None:
        return []
    if isinstance(raw, str):
        s = raw.strip()
        return [s] if s.startswith("device_tracker.") else []
    try:
        return [
            str(t).strip()
            for t in raw
            if str(t).strip().startswith("device_tracker.")
        ]
    except TypeError:
        return []
