"""Resolve mobile_app notify target from a Home Assistant person entity.

Supports three resolution strategies:
1. Legacy service: notify.mobile_app_<device_tracker_suffix>
2. Slugified friendly_name: notify.mobile_app_<slugified_friendly_name>
3. Registry-based: enumerate notify entities sharing device with person's tracker(s)
"""
from __future__ import annotations

from dataclasses import dataclass
import logging
import re
import unicodedata

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er, device_registry as dr

from .person_device_trackers import get_person_device_tracker_entity_ids

_LOGGER = logging.getLogger(__name__)


@dataclass
class NotifyTarget:
    """Result of notify resolution: how to send a push to one person."""

    mode: str  # "legacy_service" | "notify_send"
    service_name: str | None = None  # e.g. "mobile_app_brandons_iphone" for legacy
    entity_id: str | None = None  # e.g. "notify.mobile_app_brandons_iphone" for notify.send


@dataclass(frozen=True)
class NotifyPushResult:
    """Outcome of async_send_notify_push (test notification, zone health, room alerts)."""

    ok: bool
    target: str | None = None  # service name (legacy) or notify entity_id for callers / WS
    error: str | None = None  # set when ok is False


async def async_send_notify_push(
    hass: HomeAssistant,
    person_entity_id: str,
    title: str,
    message: str,
) -> NotifyPushResult:
    """Resolve mobile_app target and send push — single code path for all dashboard notifies."""
    target = resolve_notify_target(hass, person_entity_id)
    if not target:
        return NotifyPushResult(
            ok=False,
            error="No mobile_app notify target resolved. Link a phone under Settings → People.",
        )

    target_summary: str | None
    try:
        if target.mode == "legacy_service" and target.service_name:
            target_summary = target.service_name
            await hass.services.async_call(
                "notify",
                target.service_name,
                {"title": title, "message": message},
                blocking=False,
            )
            _LOGGER.debug(
                "Sent notification via %s: %s - %s", target.service_name, title, message
            )
            return NotifyPushResult(ok=True, target=target_summary)

        if target.mode == "notify_send" and target.entity_id:
            target_summary = target.entity_id
            if hass.services.has_service("notify", "send_message"):
                await hass.services.async_call(
                    "notify",
                    "send_message",
                    {"entity_id": target.entity_id, "title": title, "message": message},
                    blocking=False,
                )
            elif hass.services.has_service("notify", "send"):
                await hass.services.async_call(
                    "notify",
                    "send",
                    {
                        "entity_id": target.entity_id,
                        "title": title,
                        "message": message,
                    },
                    blocking=False,
                )
            else:
                err = (
                    f"Neither notify.send_message nor notify.send available for {target.entity_id}"
                )
                _LOGGER.warning("Cannot send push: %s", err)
                return NotifyPushResult(ok=False, target=target.entity_id, error=err)

            _LOGGER.debug(
                "Sent notification via notify entity %s: %s - %s",
                target.entity_id,
                title,
                message,
            )
            return NotifyPushResult(ok=True, target=target_summary)

        err = f"Unknown notify target mode for {person_entity_id}: {target!r}"
        _LOGGER.warning(err)
        return NotifyPushResult(ok=False, error=err)
    except Exception as e:
        _LOGGER.warning(
            "Failed to send notification to %s (target=%s): %s",
            person_entity_id,
            target,
            e,
        )
        return NotifyPushResult(
            ok=False,
            target=getattr(target, "entity_id", None) or getattr(target, "service_name", None),
            error=str(e),
        )


def slugify_device_name_for_mobile_app(name: str) -> str:
    """Build mobile_app notify suffix from a device display name (e.g. Brandon's Iphone → brandons_iphone)."""
    if not name or not str(name).strip():
        return ""
    s = unicodedata.normalize("NFKD", str(name))
    s = "".join(ch for ch in s if ch.isalnum() or ch.isspace())
    s = s.strip().lower()
    return re.sub(r"\s+", "_", s).strip("_")


def _notify_slug_registered(hass: HomeAssistant, slug: str) -> bool:
    """True when notify.mobile_app_<slug> is a registered service."""
    return bool(slug) and hass.services.has_service("notify", f"mobile_app_{slug}")


def _get_person_trackers(hass: HomeAssistant, person_entity_id: str) -> list[str]:
    """Return device_tracker.* entity ids linked to a person."""
    return get_person_device_tracker_entity_ids(hass, person_entity_id)


def _find_legacy_slug(hass: HomeAssistant, trackers: list[str]) -> str | None:
    """Try tracker entity id suffix then slugified friendly_name, return first working slug."""
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
        if fn:
            slug = slugify_device_name_for_mobile_app(str(fn))
            if _notify_slug_registered(hass, slug):
                return slug
    return None


def _find_notify_entity_via_registry(hass: HomeAssistant, trackers: list[str]) -> str | None:
    """Use entity/device registries to find a notify.* entity on the same device as a tracker."""
    ent_reg = er.async_get(hass)
    dev_reg = dr.async_get(hass)
    device_ids: set[str] = set()
    for tid in trackers:
        if not tid.startswith("device_tracker."):
            continue
        entry = ent_reg.async_get(tid)
        if entry and entry.device_id:
            device_ids.add(entry.device_id)
    if not device_ids:
        return None
    # Scan for notify entities linked to same device(s)
    for entry in ent_reg.entities.values():
        if entry.domain != "notify":
            continue
        if entry.device_id and entry.device_id in device_ids:
            # Prefer mobile_app flavors
            if "mobile_app" in entry.entity_id:
                return entry.entity_id
    # Second pass: any notify entity
    for entry in ent_reg.entities.values():
        if entry.domain != "notify":
            continue
        if entry.device_id and entry.device_id in device_ids:
            return entry.entity_id
    return None


def _find_notify_entity_from_tracker_ids(
    hass: HomeAssistant, trackers: list[str]
) -> str | None:
    """Match notify.mobile_app_<device_tracker_object_id> when registry has no device link."""
    ent_reg = er.async_get(hass)
    for tid in trackers:
        if not tid.startswith("device_tracker."):
            continue
        suffix = tid.split(".", 1)[1].lower()
        nid = f"notify.mobile_app_{suffix}"
        if ent_reg.async_get(nid) is not None or hass.states.get(nid) is not None:
            return nid
    return None


def resolve_notify_target(hass: HomeAssistant, person_entity_id: str) -> NotifyTarget | None:
    """Return the best NotifyTarget for a person or None if unavailable.

    Tries:
    1. Legacy notify.mobile_app_<slug> service
    2. Entity-based notify via notify.send_message or notify.send
    """
    trackers = _get_person_trackers(hass, person_entity_id)
    # 1. Legacy service path
    slug = _find_legacy_slug(hass, trackers)
    if slug:
        return NotifyTarget(mode="legacy_service", service_name=f"mobile_app_{slug}")

    # 2. Entity-based: registry (device-linked), then notify.mobile_app_<tracker> state
    entity_id = _find_notify_entity_via_registry(hass, trackers)
    if not entity_id:
        entity_id = _find_notify_entity_from_tracker_ids(hass, trackers)
    if entity_id and (
        hass.services.has_service("notify", "send_message")
        or hass.services.has_service("notify", "send")
    ):
        return NotifyTarget(mode="notify_send", entity_id=entity_id)

    # Log diagnostic info
    candidate = entity_id or "(none found via registry)"
    has_send = hass.services.has_service("notify", "send_message") or hass.services.has_service(
        "notify", "send"
    )
    if trackers:
        _LOGGER.warning(
            "No notify target resolved for %s (trackers=%s, registry_candidate=%s, notify.send_message=%s). "
            "Link the phone in Settings → People and ensure the Companion app is registered.",
            person_entity_id,
            trackers,
            candidate,
            has_send,
        )
    else:
        _LOGGER.warning(
            "No device_trackers on %s; cannot resolve mobile_app notify target. "
            "Link a device in Settings → People.",
            person_entity_id,
        )
    return None


def resolve_mobile_app_notify_slug(hass: HomeAssistant, person_entity_id: str) -> str | None:
    """Legacy helper: return slug for notify.mobile_app_<slug> or None.

    Kept for backward compatibility; callers wanting full resolution should use
    resolve_notify_target() instead.
    """
    trackers = _get_person_trackers(hass, person_entity_id)
    slug = _find_legacy_slug(hass, trackers)
    if slug:
        return slug
    # Log once
    if trackers:
        _LOGGER.debug(
            "Legacy resolve_mobile_app_notify_slug returned None for %s (trackers=%s).",
            person_entity_id,
            trackers,
        )
    return None
