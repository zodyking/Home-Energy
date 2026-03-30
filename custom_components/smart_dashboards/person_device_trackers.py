"""Resolve device_tracker.* entity IDs linked to a person (Person integration + state fallback)."""
from __future__ import annotations

from homeassistant.core import HomeAssistant


def get_person_device_tracker_entity_ids(
    hass: HomeAssistant, person_entity_id: str
) -> list[str]:
    """Return device_tracker.* linked to a person.

    Merges homeassistant.components.person.entities_in_person (config source) with
    person state attributes ``device_trackers`` so we never drop trackers when one
    source is empty, lagging, or out of sync (fixes intermittent notify resolution).
    """
    seen: set[str] = set()
    ordered: list[str] = []

    def _add(ids: list[str]) -> None:
        for eid in ids:
            s = str(eid).strip().lower()
            if not s.startswith("device_tracker."):
                continue
            if s not in seen:
                seen.add(s)
                ordered.append(s)

    try:
        from homeassistant.components.person import entities_in_person
    except ImportError:
        entities_in_person = None

    person_key = str(person_entity_id).strip().lower()

    if entities_in_person is not None:
        linked = entities_in_person(hass, person_key)
        if linked:
            _add([str(t).strip() for t in linked])

    ps = hass.states.get(person_key)
    if ps:
        raw = ps.attributes.get("device_trackers")
        if raw is not None:
            if isinstance(raw, str):
                _add([raw.strip()])
            else:
                try:
                    _add([str(t).strip() for t in raw])
                except TypeError:
                    pass

    return ordered
