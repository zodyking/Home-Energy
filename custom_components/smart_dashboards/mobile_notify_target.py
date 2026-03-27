"""Resolve notify.mobile_app_* service suffix from a Home Assistant person entity."""
from __future__ import annotations

import logging
import re
import unicodedata

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


def slugify_device_name_for_mobile_app(name: str) -> str:
    """Build mobile_app notify suffix from a device display name (e.g. Brandon's Iphone → brandons_iphone)."""
    if not name or not str(name).strip():
        return ""
    s = unicodedata.normalize("NFKD", str(name))
    s = "".join(ch for ch in s if ch.isalnum() or ch.isspace())
    s = s.strip().lower()
    return re.sub(r"\s+", "_", s).strip("_")


def _notify_slug_registered(hass: HomeAssistant, slug: str) -> bool:
    return bool(slug) and hass.services.has_service("notify", f"mobile_app_{slug}")


def resolve_mobile_app_notify_slug(hass: HomeAssistant, person_entity_id: str) -> str | None:
    """Pick notify.mobile_app_<slug> for a person using linked device_tracker entities.

    Uses each tracker's entity_id suffix first (matches Companion app + HA naming), then
    slugified friendly_name of that tracker. Does not use the person's own name/username.
    """
    state = hass.states.get(person_entity_id)
    if not state:
        return None

    raw = state.attributes.get("device_trackers")
    if raw is None:
        trackers: list[str] = []
    elif isinstance(raw, str):
        trackers = [raw] if raw.strip() else []
    else:
        try:
            trackers = [str(t).strip() for t in raw if str(t).strip()]
        except TypeError:
            trackers = []

    for tid in trackers:
        if not tid.startswith("device_tracker."):
            continue
        slug = tid.split(".", 1)[1].lower()
        if _notify_slug_registered(hass, slug):
            return slug

    for tid in trackers:
        if not tid.startswith("device_tracker."):
            continue
        ts = hass.states.get(tid)
        if not ts:
            continue
        fn = ts.attributes.get("friendly_name")
        if not fn:
            continue
        slug = slugify_device_name_for_mobile_app(str(fn))
        if _notify_slug_registered(hass, slug):
            return slug

    if trackers:
        _LOGGER.warning(
            "No notify.mobile_app_* service found for %s (device_trackers=%s). "
            "Link the phone in Settings → People and ensure the Companion app is registered.",
            person_entity_id,
            trackers,
        )
    else:
        _LOGGER.warning(
            "No device_trackers on %s; cannot resolve mobile_app notify target. "
            "Link a device in Settings → People.",
            person_entity_id,
        )
    return None
