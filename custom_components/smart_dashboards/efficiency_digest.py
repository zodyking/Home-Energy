"""Daily optional push digest of room efficiency scores (rooms with ``person.*`` assigned)."""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_change
from homeassistant.util import dt as dt_util

from .config_manager import _coerce_bool, _normalize_presence_person_entity
from .const import DEFAULT_NOTIFICATION_TITLE, DEFAULT_TTS_PREFIX, DOMAIN
from .mobile_notify_target import async_send_notify_push
from .room_ratings import canonical_room_id, compute_intraday_ratings

_LOGGER = logging.getLogger(__name__)

STATE_FILE = "efficiency_digest_state.json"

PILLAR_KEYS = ("compliance", "warning", "consumption", "load", "engagement")

PILLAR_LABELS: dict[str, str] = {
    "compliance": "Compliance",
    "warning": "Warnings",
    "consumption": "Consumption",
    "load": "Load",
    "engagement": "Engagement",
}

PILLAR_TIPS: dict[str, str] = {
    "compliance": "Try to stay under your daily budget.",
    "warning": "Reduce threshold warnings and shutoffs.",
    "consumption": "Usage is high vs your other rooms.",
    "load": "Avoid sustained high-power draws.",
    "engagement": "Open this dashboard a bit more often.",
}


def _parse_digest_hhmm(s: str) -> tuple[int, int]:
    m = re.match(r"^(\d{1,2}):(\d{2})$", str(s or "").strip())
    if not m:
        return 8, 0
    h, mi = int(m.group(1)), int(m.group(2))
    if not (0 <= h <= 23 and 0 <= mi <= 59):
        return 8, 0
    return h, mi


def _load_digest_state(path: str) -> dict[str, Any]:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        return raw if isinstance(raw, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_digest_state(path: str, data: dict[str, Any]) -> None:
    from .json_store import atomic_save_json
    atomic_save_json(path, data)


def _digest_tts_prefix(tts: dict[str, Any]) -> str:
    raw = tts.get("prefix")
    s = str(raw if raw is not None else DEFAULT_TTS_PREFIX).strip()
    return s or DEFAULT_TTS_PREFIX


def _intraday_ratings_by_room(hass: HomeAssistant, cm: Any) -> dict[str, dict[str, Any]]:
    """Same intraday scores as the room tab (get_power_data)."""
    from .websocket import build_rooms_payload_for_power_and_ratings

    try:
        rooms_payload = build_rooms_payload_for_power_and_ratings(hass, cm)
        return compute_intraday_ratings(hass, cm, rooms_payload)
    except Exception as err:
        _LOGGER.warning("Efficiency digest intraday ratings failed: %s", err)
        return {}


def _format_vars(
    room_name: str,
    r: dict[str, Any],
    notification_title: str,
    prefix: str,
) -> dict[str, Any]:
    def _fmt(v: Any) -> str:
        if v is None:
            return "—"
        if isinstance(v, float):
            return str(v).rstrip("0").rstrip(".") if "." in str(v) else str(v)
        return str(v)

    pillar_meta = r.get("pillar_meta") if isinstance(r.get("pillar_meta"), dict) else {}
    candidates: list[tuple[str, float]] = []
    for k in PILLAR_KEYS:
        if pillar_meta.get(k) in ("na", "no_data"):
            continue
        raw = r.get(k)
        try:
            score = float(raw)
        except (TypeError, ValueError):
            continue
        candidates.append((k, score))

    if candidates:
        worst_key = min(candidates, key=lambda x: x[1])[0]
    else:
        worst_key = "compliance"

    worst_pillar = PILLAR_LABELS.get(worst_key, worst_key.capitalize())
    worst_pillar_tip = PILLAR_TIPS.get(worst_key, PILLAR_TIPS["compliance"])

    return {
        "prefix": prefix,
        "notification_title": notification_title,
        "room_name": room_name,
        "average": _fmt(r.get("average")),
        "stars": _fmt(r.get("stars")),
        "compliance": _fmt(r.get("compliance")),
        "warning": _fmt(r.get("warning")),
        "consumption": _fmt(r.get("consumption")),
        "load": _fmt(r.get("load")),
        "engagement": _fmt(r.get("engagement")),
        "worst_pillar": worst_pillar,
        "worst_pillar_tip": worst_pillar_tip,
    }


async def _run_efficiency_digest(hass: HomeAssistant) -> None:
    domain = hass.data.get(DOMAIN)
    if not domain:
        return
    cm = domain.get("config_manager")
    if not cm:
        return
    es = cm.energy_config.get("efficiency_settings") or {}
    tts = cm.energy_config.get("tts_settings") or {}
    if not _coerce_bool(es.get("efficiency_digest_enabled"), False):
        return

    now = dt_util.now()
    today = now.strftime("%Y-%m-%d")
    state_path = cm._data_path(STATE_FILE)

    def _read_state() -> dict[str, Any]:
        return _load_digest_state(state_path)

    state = await hass.async_add_executor_job(_read_state)
    if state.get("last_sent") == today:
        return

    intraday = _intraday_ratings_by_room(hass, cm)

    notification_title = str(
        tts.get("notification_title") or DEFAULT_NOTIFICATION_TITLE
    ).strip() or DEFAULT_NOTIFICATION_TITLE
    prefix = _digest_tts_prefix(tts)

    title_tmpl = str(es.get("efficiency_digest_title") or "")
    msg_tmpl = str(es.get("efficiency_digest_message") or "")

    rooms_cfg = cm.energy_config.get("rooms") or []
    eligible_rooms = 0
    successful_sends = 0
    for room in rooms_cfg:
        if not isinstance(room, dict):
            continue
        person_eid = _normalize_presence_person_entity(room.get("presence_person_entity"))
        if not person_eid:
            continue
        eligible_rooms += 1
        rid = canonical_room_id(room)
        r = intraday.get(rid) if isinstance(intraday.get(rid), dict) else {}
        room_name = str(room.get("name") or rid)
        vars_ = _format_vars(room_name, r, notification_title, prefix)
        try:
            title = title_tmpl.format(**vars_)
            message = msg_tmpl.format(**vars_)
        except (KeyError, ValueError) as err:
            _LOGGER.warning("Efficiency digest template error for %s: %s", rid, err)
            title = f"{notification_title} {room_name}"
            message = (
                f"{room_name}: {vars_['stars']} stars ({vars_['average']}/100). "
                f"{vars_['worst_pillar_tip']}"
            )
        result = await async_send_notify_push(hass, person_eid, title, message)
        if result.ok:
            successful_sends += 1
        else:
            _LOGGER.warning(
                "Efficiency digest push failed for %s (%s): %s",
                rid,
                person_eid,
                result.error,
            )

    # Same send path as digest test; avoid marking the day "done" if every send failed
    # (allows retry after restart). No eligible rooms → mark sent to skip repeat work.
    if successful_sends > 0 or eligible_rooms == 0:

        def _write() -> None:
            _save_digest_state(state_path, {"last_sent": today})

        await hass.async_add_executor_job(_write)


async def async_reschedule_efficiency_digest(hass: HomeAssistant) -> None:
    domain = hass.data.setdefault(DOMAIN, {})
    old = domain.get("efficiency_digest_unsub")
    if callable(old):
        old()
    domain["efficiency_digest_unsub"] = None

    cm = domain.get("config_manager")
    if not cm:
        return

    es = cm.energy_config.get("efficiency_settings") or {}
    if not _coerce_bool(es.get("efficiency_digest_enabled"), False):
        return

    hour, minute = _parse_digest_hhmm(str(es.get("efficiency_digest_time") or "08:00"))

    @callback
    def _on_digest_time(_dt: Any) -> None:
        hass.async_create_task(_run_efficiency_digest(hass))

    unsub = async_track_time_change(
        hass,
        _on_digest_time,
        hour=hour,
        minute=minute,
        second=0,
    )
    domain["efficiency_digest_unsub"] = unsub


async def async_setup_efficiency_digest(hass: HomeAssistant) -> None:
    await async_reschedule_efficiency_digest(hass)


async def async_send_efficiency_digest_test(
    hass: HomeAssistant,
    target_person: str,
    room_id: str | None = None,
) -> tuple[bool, str | None]:
    """Send one digest-style notification (does not update last_sent)."""
    domain = hass.data.get(DOMAIN) or {}
    cm = domain.get("config_manager")
    if not cm:
        return False, "Config manager not initialized"
    target_person = str(target_person).strip().lower()
    if not target_person.startswith("person."):
        return False, "target_person must be a person.* entity"
    person_state = hass.states.get(target_person)
    if not person_state:
        return False, f"Person entity not found: {target_person}"

    intraday = _intraday_ratings_by_room(hass, cm)

    tts = cm.energy_config.get("tts_settings") or {}
    es = cm.energy_config.get("efficiency_settings") or {}
    notification_title = str(
        tts.get("notification_title") or DEFAULT_NOTIFICATION_TITLE
    ).strip() or DEFAULT_NOTIFICATION_TITLE
    prefix = _digest_tts_prefix(tts)
    title_tmpl = str(es.get("efficiency_digest_title") or "")
    msg_tmpl = str(es.get("efficiency_digest_message") or "")

    rooms_cfg = cm.energy_config.get("rooms") or []
    chosen: dict[str, Any] | None = None
    rid_key: str | None = None

    if room_id and str(room_id).strip():
        want = str(room_id).strip()
        for room in rooms_cfg:
            if not isinstance(room, dict):
                continue
            if canonical_room_id(room) != want:
                continue
            pe = _normalize_presence_person_entity(room.get("presence_person_entity"))
            if pe != target_person:
                return False, "Room's assigned person does not match target person"
            chosen = room
            rid_key = want
            break
        if chosen is None:
            return False, f"No room with id {want!r}"
    else:
        for room in rooms_cfg:
            if not isinstance(room, dict):
                continue
            pe = _normalize_presence_person_entity(room.get("presence_person_entity"))
            if pe == target_person:
                chosen = room
                rid_key = canonical_room_id(room)
                break
        if chosen is None:
            return False, "No room uses this person as presence_person_entity"

    r = (
        intraday.get(rid_key or "")
        if isinstance(intraday.get(rid_key or ""), dict)
        else {}
    )
    room_name = str(chosen.get("name") or rid_key)
    vars_ = _format_vars(room_name, r, notification_title, prefix)
    try:
        title = title_tmpl.format(**vars_)
        message = msg_tmpl.format(**vars_)
    except (KeyError, ValueError) as err:
        _LOGGER.warning("Efficiency digest test template error: %s", err)
        title = f"{notification_title} {room_name}"
        message = (
            f"{room_name}: {vars_['stars']} stars ({vars_['average']}/100). "
            f"{vars_['worst_pillar_tip']}"
        )

    result = await async_send_notify_push(hass, target_person, title, message)
    if result.ok:
        return True, None
    return False, result.error or "Send failed"
