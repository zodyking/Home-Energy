"""Energy monitoring background task for Smart Dashboards."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from collections import defaultdict, deque
from datetime import datetime, timedelta
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState, Event, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later, async_track_state_change_event
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    ALERT_COOLDOWN,
    DEFAULT_BUDGET_EXCEEDED_MSG,
    DEFAULT_BUDGET_BOOST_SCHEDULED_MSG,
    ENERGY_CHECK_INTERVAL,
    ROOM_BOOST_DAYS_REMINDER_INTERVAL_SECONDS,
    SHUTOFF_RESET_DELAY,
    STOVE_WARNING_TIMER,
    STOVE_SHUTOFF_TIMER,
    DEFAULT_TTS_PREFIX,
    DEFAULT_ROOM_WARN_MSG,
    DEFAULT_OUTLET_WARN_MSG,
    DEFAULT_SHUTOFF_MSG,
    DEFAULT_BREAKER_WARN_MSG,
    DEFAULT_BREAKER_SHUTOFF_MSG,
    DEFAULT_STOVE_ON_MSG,
    DEFAULT_STOVE_OFF_MSG,
    DEFAULT_STOVE_TIMER_STARTED_MSG,
    DEFAULT_STOVE_15MIN_WARN_MSG,
    DEFAULT_STOVE_30SEC_WARN_MSG,
    DEFAULT_STOVE_TIMER_PROGRESS_MSG,
    DEFAULT_STOVE_AUTO_OFF_MSG,
    DEFAULT_MICROWAVE_CUT_MSG,
    DEFAULT_MICROWAVE_RESTORE_MSG,
    DEFAULT_MINISPLIT_PHASE2_WARN_MSG,
    DEFAULT_MINISPLIT_PHASE2_AFTER_MSG,
    DEFAULT_MINISPLIT_PHASE2_RESTORE_MSG,
    DEFAULT_HEATER_AUTOMATION_ON_MSG,
    DEFAULT_VENT_AUTOMATION_ON_MSG,
    DEFAULT_NOTIFY_AC_AUTO_OFF_MSG,
    DEFAULT_NOTIFY_AC_AUTO_ON_MSG,
    DEFAULT_NOTIFY_MANUAL_TOGGLE_MSG,
    DEFAULT_NOTIFICATION_TITLE,
    DEFAULT_DOOR_OPENED_MSG,
    DEFAULT_DOOR_CLOSED_MSG,
    DEFAULT_DOOR_LOCKED_MSG,
    DEFAULT_DOOR_UNLOCKED_MSG,
    DEFAULT_DOOR_STILL_OPEN_MSG,
    DEFAULT_DOOR_STILL_UNLOCKED_MSG,
    DEFAULT_WINDOW_OPENED_MSG,
    DEFAULT_WINDOW_CLOSED_MSG,
    DEFAULT_WINDOW_STILL_OPEN_MSG,
    DEFAULT_PRESENCE_DETECTED_MSG,
    DEFAULT_PRESENCE_CLEARED_MSG,
)
from .mobile_notify_target import resolve_notify_target
from .zone_health_storage import (
    append_snapshot,
    ensure_person_entry,
    load_store,
    prune_snapshots,
    save_store,
    union_states_from_snapshots,
    warmup_complete,
    warmup_complete_at_iso,
    zone_health_store_path,
)
from .config_manager import (
    ConfigManager,
    _coerce_bool,
    _normalize_presence_person_entity,
    resolve_budget_boost_weekdays,
    resolve_wall_heater_effective_temperatures,
)
from .person_device_trackers import get_person_device_tracker_entity_ids
from .tts_helper import async_send_tts
from .tts_queue import async_send_tts_or_queue
from .tts_numbers import spoken_cardinal

_LOGGER = logging.getLogger(__name__)


def _format_tts_msg(template: str | None, **kwargs: object) -> str:
    """Format a user TTS template; placeholders not in kwargs resolve to empty string."""
    t = str(template or "")
    if not t:
        return ""
    m: defaultdict[str, str] = defaultdict(str)
    for k, v in kwargs.items():
        m[str(k)] = "" if v is None else str(v)
    try:
        return t.format_map(m).strip()
    except ValueError:
        return t.strip()


def _normalize_light_entity_row(light: object) -> tuple[str | None, bool, bool]:
    """Resolve (entity_id, wrgb, tuya) from a light_entities row (dict or legacy string)."""
    if isinstance(light, str):
        eid = light.strip()
        if eid.startswith("light."):
            return eid, False, False
        return None, False, False
    if isinstance(light, dict):
        eid = str(light.get("entity_id") or "").strip()
        if eid.startswith("light."):
            return eid, bool(light.get("wrgb")), bool(light.get("tuya"))
    return None, False, False


def person_in_any_configured_zone(
    hass: HomeAssistant, person_entity_id: str, zone_entity_ids: list[str]
) -> bool:
    """True if person state matches any configured zone (friendly name, slug, or home)."""
    if not person_entity_id or not zone_entity_ids:
        return True
    ps = hass.states.get(person_entity_id)
    if not ps or ps.state in ("unknown", "unavailable", ""):
        return False
    raw = (ps.state or "").strip().lower()
    if raw == "not_home":
        return False
    for zid in zone_entity_ids:
        zs = hass.states.get(zid)
        if not zs or not str(zid).startswith("zone."):
            continue
        fn = str(zs.attributes.get("friendly_name") or "").strip().lower()
        slug = zid.split(".", 1)[-1].replace("_", " ").lower()
        zid_l = zid.lower()
        if fn and raw == fn:
            return True
        if raw == slug or raw == zid_l or raw == zid.split(".", 1)[-1].lower():
            return True
        if zid == "zone.home" and raw == "home":
            return True
    return False


def person_in_home_or_nearby(hass: HomeAssistant, person_entity_id: str) -> bool:
    """True if person is in zone.home or zone.nearby (entities must exist in registry)."""
    for zid in ("zone.home", "zone.nearby"):
        zs = hass.states.get(zid)
        if not zs or not str(zid).startswith("zone."):
            continue
        if person_in_any_configured_zone(hass, person_entity_id, [zid]):
            return True
    return False


def person_truly_away_for_ac(hass: HomeAssistant, person_entity_id: str) -> bool:
    """True when user left the comfort area: not in home or nearby (and not unknown).

    Moving home→nearby stays in comfort so AC auto-off does not fire; only real departure does.
    """
    if not person_entity_id:
        return False
    ps = hass.states.get(person_entity_id)
    if not ps or ps.state in ("unknown", "unavailable", ""):
        return False
    raw = (ps.state or "").strip().lower()
    if raw == "not_home":
        return True
    if person_in_home_or_nearby(hass, person_entity_id):
        return False
    return True


def _presence_zone_match_tokens(hass: HomeAssistant, zone_entity_id: str) -> frozenset[str]:
    """Lowercase strings that mean the person/tracker is in this zone entity."""
    zid = str(zone_entity_id or "").strip().lower()
    if not zid.startswith("zone."):
        return frozenset()
    object_id = zid.replace("zone.", "", 1)
    tokens: set[str] = {zid, object_id, object_id.replace("_", " ")}
    zs = hass.states.get(zid)
    if zs:
        fn = str(zs.attributes.get("friendly_name") or "").strip().lower()
        if fn:
            tokens.add(fn)
        if zid == "zone.home":
            tokens.add("home")
    return frozenset(t for t in tokens if t)


def _person_state_matches_presence_zone(raw_state: str, tokens: frozenset[str]) -> bool:
    s = (raw_state or "").strip().lower()
    if s.startswith("at "):
        s = s[3:].strip()
    return bool(s and s in tokens)


def person_in_room_presence_zones(
    hass: HomeAssistant,
    person_entity_id: str,
    zone_entity_ids: list[str],
) -> bool:
    """True when person is in any room-configured zone (matches UI: any selected zone = present).

    Uses device-tracker GPS inside zone circles first (handles person.state lag / not_home glitches),
    then person.state string matching including zone slugs (e.g. brandons_nearby).
    """
    if not person_entity_id:
        return False
    zone_ids = [
        str(z).strip().lower()
        for z in (zone_entity_ids or [])
        if z and str(z).strip().lower().startswith("zone.")
    ]
    if not zone_ids:
        return False

    try:
        from homeassistant.components.zone import in_zone
    except ImportError:
        in_zone = None

    if in_zone is not None:
        for tracker in get_person_device_tracker_entity_ids(hass, person_entity_id):
            ts = hass.states.get(tracker)
            if not ts or ts.state in ("unknown", "unavailable", ""):
                continue
            lat = ts.attributes.get("latitude")
            lon = ts.attributes.get("longitude")
            if lat is None or lon is None:
                continue
            try:
                lat_f, lon_f = float(lat), float(lon)
            except (TypeError, ValueError):
                continue
            for zid in zone_ids:
                zs = hass.states.get(zid)
                if zs and in_zone(zs, lat_f, lon_f):
                    return True

    ps = hass.states.get(person_entity_id)
    if not ps or ps.state in ("unknown", "unavailable", ""):
        return False
    raw = (ps.state or "").strip().lower()
    if raw == "not_home":
        return False
    if person_in_any_configured_zone(hass, person_entity_id, zone_ids):
        return True
    for zid in zone_ids:
        if _person_state_matches_presence_zone(raw, _presence_zone_match_tokens(hass, zid)):
            return True
    return False


def vent_like_energy_tracking_key(room_id: str, outlet: dict) -> str:
    """Match config_manager.vent_like_energy_tracking_key for static-watt vent/heater loads."""
    name = (outlet.get("name") or "device").lower().replace(" ", "_")
    if outlet.get("type") == "wall_heater":
        return f"wall_heater_{room_id}_{name}"
    return f"ceiling_vent_{room_id}_{name}"


class EnergyMonitor:
    """Monitor energy consumption and send TTS alerts for thresholds."""

    _DOOR_ACTIVITY_RETENTION = timedelta(hours=72)
    # After a schedule segment becomes active, re-apply at most this long (then idle until next transition).
    _LIGHT_AUTO_BURST_ENFORCE_SEC = 60.0

    def __init__(self, hass: HomeAssistant, config_manager: "ConfigManager") -> None:
        """Initialize the energy monitor."""
        self.hass = hass
        self.config_manager = config_manager
        self._running = False
        self._task: asyncio.Task | None = None
        self._last_room_alerts: dict[str, datetime] = {}
        self._last_outlet_alerts: dict[str, datetime] = {}
        self._last_plug_alerts: dict[str, datetime] = {}
        self._last_breaker_warnings: dict[str, datetime] = {}
        self._last_breaker_shutoffs: dict[str, datetime] = {}
        self._breaker_shutoff_pending: dict[str, bool] = {}  # Track breakers in shutoff cycle
        self._shutoff_pending: dict[str, bool] = {}  # Track plugs in shutoff cycle
        self._save_counter = 0
        
        # Stove safety state (keyed by stove_plug_entity for multi-stove support)
        self._stove_state: dict[str, str] = {}
        self._stove_timer_start: dict[str, datetime | None] = {}
        self._stove_timer_phase: dict[str, str] = {}
        self._stove_last_presence: dict[str, str | None] = {}
        self._stove_15min_warn_sent: dict[str, bool] = {}
        self._stove_30sec_warn_sent: dict[str, bool] = {}
        self._stove_powered_off_by_microwave: dict[str, bool] = {}
        self._stove_power_below_since: dict[str, datetime | None] = {}
        self._stove_power_above_since: dict[str, datetime | None] = {}
        self._stove_presence_window_start: dict[str, datetime | None] = {}
        self._power_listener_unsub: list = []  # Unsubscribe callbacks for state listeners
        self._presence_listener_unsub: list = []  # person.* + zone.* for presence automation
        self._room_budget_announced: set[str] = set()
        self._room_budget_announced_date: str = ""
        self._room_boost_days_last_reminder_at: dict[str, datetime] = {}
        self._budget_boost_scheduled_fired_date: str = ""
        self._budget_boost_slots_fired: dict[str, list[int]] = {}
        self._stove_progress_last_boundary: dict[str, int] = {}
        # Phase-2 mini-split hold: room_id -> {switches: set[str], outlet_name, volume}
        self._minisplit_hold: dict[str, dict] = {}
        # Presence / AC comfort: last known in-room zone presence per room_id
        self._room_presence_was_in_comfort: dict[str, bool | None] = {}
        # Switches we turned off due to leaving zones (restore on return if still allowed)
        self._presence_auto_turned_off: dict[str, set[str]] = {}
        self._presence_room_locks: dict[str, asyncio.Lock] = {}
        # Vent / wall heater optional automations (key: room_id|outlet_name_slug)
        self._vent_automation_state: dict[str, dict] = {}
        self._heater_automation_state: dict[str, dict] = {}
        # Smart heater state with thermal learning (key: room_id|outlet_name_slug)
        self._heater_smart_state: dict[str, dict] = {}
        # Light automation state (tracks last applied action per light)
        self._light_automation_state: dict[str, str] = {}
        # Entities skipped while unavailable (debug log once until usable again)
        self._light_auto_unavail_logged: set[str] = set()
        # Light automation enforcement pause (for testing scenes)
        self._light_enforcement_paused_until: float = 0.0
        # Light automation last enforcement time per entity
        self._light_enforcement_last_run: dict[str, float] = {}
        # switch.* the integration toggled recently (exclude from external automation detection)
        self._integration_internal_switch_ids: set[str] = set()
        # Universal push: switch.* state listener + suppression during internal cycling
        self._manual_toggle_listener_unsub: list = []
        # Re-entrant count per room (minisplit path calls _power_cycle nested)
        self._enforcement_power_cycle_depth: dict[str, int] = {}
        self._plug_shutoff_switch_entities: set[str] = set()
        self._manual_toggle_notify_last: dict[str, datetime] = {}
        self._person_zone_health_alerted: set[str] = set()
        self._person_zone_health_listener_unsub: list = []
        self._person_zone_hourly_reminder_last: dict[str, datetime] = {}
        # Zone health event log for UI display (recent alerts/TTS/recoveries)
        self._zone_health_event_log: deque = deque(maxlen=100)
        # Zone health recorder-backed history (refreshed periodically)
        self._zone_health_recorder_cache: dict[str, set[str]] = {}
        self._zone_health_tracker_recorder_cache: dict[str, dict[str, set[str]]] = {}
        self._zone_health_recorder_meta: dict[str, dict[str, str | None]] = {}
        self._zone_health_recorder_last_refresh: datetime | None = None
        # Recorder queries are heavy; automatic refresh at most this often. Real-time path uses
        # Zone-health state listeners (recovery TTS); recorder pull uses device_trackers only. "Refresh Status" forces pull.
        self._zone_health_recorder_refresh_interval = timedelta(hours=1)
        self._zone_health_tts_lock = asyncio.Lock()
        # "Nearby" zone guidance: track whether we've already created/dismissed the persistent_notification
        self._nearby_zone_notification_shown: bool = False
        # Zone health: defer TTS/push/recovery until HA has been up 10 minutes (recorder / mobile_app settle)
        self._zone_health_ha_started_at: datetime | None = None
        self._zone_health_earliest_alert_at: datetime | None = None
        # In-memory copy of JSON store (kept in sync with disk after each recorder refresh)
        self._zone_health_store_cache: dict | None = None

        # Door/Window/Lock/Presence automation state
        # NOTE: _door_window_state, _lock_state, and _presence_hold_state were
        # previously declared but never read or written — the handlers re-read
        # hass.states each time. They are removed (audit BUG 7).
        self._door_reminder_active: dict[str, asyncio.Task | None] = {}  # active reminder tasks
        self._door_auto_lock_task: dict[str, asyncio.Task | None] = {}  # pending auto-lock tasks
        # Cancellable presence hold-then-announce tasks (audit BUG 4).
        self._presence_handler_tasks: dict[str, asyncio.Task | None] = {}
        self._door_window_listener_unsub: list = []  # unsubscribe callbacks for contact sensors
        self._lock_listener_unsub: list = []  # unsubscribe callbacks for lock entities
        self._door_presence_listener_unsub: list = []  # unsubscribe callbacks for door/window presence sensors
        # Battery monitoring state
        self._battery_last_level: dict[str, float] = {}  # last known battery level per sensor entity
        self._battery_low_warn_last: dict[str, datetime] = {}  # last hourly low battery warning per sensor
        self._battery_listener_unsub: list = []  # unsubscribe callbacks for battery sensors
        # Last contact/lock state we acted on (dedupe HA replay + duplicate same-state events)
        self._door_window_last_signal_state: dict[str, str] = {}
        # Door contact/lock activity for dashboard (in-memory; max 72h per door key)
        self._door_activity_log: dict[str, list[dict[str, str]]] = {}
        # group:{room_id} / ind:{room_id}:{entity_id} -> segment transition + burst reconcile timing
        self._light_auto_apply_state: dict[str, dict] = {}

    @staticmethod
    def _notification_enable_key(notification_type: str) -> str:
        if notification_type == "budget_hit":
            return "notify_room_budget_hit"
        if notification_type == "room_boost_days":
            return "notify_room_boost_days"
        if notification_type in ("enforcement_phase1", "enforcement_phase2"):
            return "notify_enforcement_phase_change"
        if notification_type in ("heater_auto_on", "heater_auto_off"):
            return "notify_heater_auto"
        if notification_type in ("vent_auto_on", "vent_auto_off"):
            return "notify_vent_auto"
        return f"notify_{notification_type}"

    @staticmethod
    def _notification_template_keys(notification_type: str) -> tuple[str, str]:
        if notification_type == "budget_hit":
            return "notify_budget_hit_title", "notify_budget_hit_msg"
        if notification_type == "room_boost_days":
            return "notify_room_boost_days_title", "notify_room_boost_days_msg"
        return (
            f"notify_{notification_type}_title",
            f"notify_{notification_type}_msg",
        )

    def _all_configured_outlet_switch_ids(self) -> set[str]:
        """switch.* entities referenced by room/outlet config (for manual-toggle notify)."""
        found: set[str] = set()
        for room in self.config_manager.energy_config.get("rooms", []):
            for outlet in room.get("outlets", []):
                for key in ("plug1_switch", "plug2_switch", "switch_entity"):
                    eid = outlet.get(key)
                    if eid and str(eid).startswith("switch."):
                        found.add(str(eid))
        return found

    def _room_outlet_context_for_switch(
        self, entity_id: str
    ) -> tuple[str, str, str, str] | None:
        """Return room_id, room_name, outlet_display_name, plug_slot for a switch.* or None."""
        for room in self.config_manager.energy_config.get("rooms", []):
            outlet = self._find_outlet_by_switch(room, entity_id)
            if not outlet:
                continue
            room_id = room.get("id", room["name"].lower().replace(" ", "_"))
            room_name = str(room.get("name") or room_id)
            outlet_name = str(outlet.get("name") or "Outlet")
            plug_slot = ""
            if outlet.get("plug1_switch") == entity_id:
                plug_slot = str(outlet.get("plug1_name") or "plug 1")
            elif outlet.get("plug2_switch") == entity_id:
                plug_slot = str(outlet.get("plug2_name") or "plug 2")
            parts = [outlet_name, plug_slot] if plug_slot else [outlet_name]
            display = " ".join(p for p in parts if p).strip()
            return room_id, room_name, display, plug_slot
        return None

    def _room_outlet_context_for_switch_with_type(
        self, entity_id: str
    ) -> tuple[str, str, str, str, str] | None:
        """Return room_id, room_name, outlet_display_name, plug_slot, outlet_type for a switch.* or None."""
        for room in self.config_manager.energy_config.get("rooms", []):
            outlet = self._find_outlet_by_switch(room, entity_id)
            if not outlet:
                continue
            room_id = room.get("id", room["name"].lower().replace(" ", "_"))
            room_name = str(room.get("name") or room_id)
            outlet_name = str(outlet.get("name") or "Outlet")
            outlet_type = str(outlet.get("type") or "outlet")
            plug_slot = ""
            if outlet.get("plug1_switch") == entity_id:
                plug_slot = str(outlet.get("plug1_name") or "plug 1")
            elif outlet.get("plug2_switch") == entity_id:
                plug_slot = str(outlet.get("plug2_name") or "plug 2")
            parts = [outlet_name, plug_slot] if plug_slot else [outlet_name]
            display = " ".join(p for p in parts if p).strip()
            return room_id, room_name, display, plug_slot, outlet_type
        return None

    def _distinct_presence_person_entity_ids(self) -> list[str]:
        """Unique person.* from all rooms (targets for universal notifications)."""
        seen: set[str] = set()
        ordered: list[str] = []
        for room in self.config_manager.energy_config.get("rooms", []):
            pe = room.get("presence_person_entity")
            if not pe:
                continue
            pe_norm = str(pe).strip().lower()
            if not pe_norm.startswith("person."):
                continue
            if pe_norm not in seen:
                seen.add(pe_norm)
                ordered.append(pe_norm)
        return ordered

    def _anyone_in_any_zone(self) -> bool:
        """Return True if at least one configured person is in any zone (not 'not_home').

        Used to pause heater/vent automation when the house is empty.
        Returns True if no persons are configured (don't block automation).
        """
        all_persons = self._distinct_presence_person_entity_ids()
        if not all_persons:
            return True
        for person_ent in all_persons:
            ps = self.hass.states.get(person_ent)
            if ps and ps.state not in ("not_home", "unknown", "unavailable", ""):
                return True
        return False

    def _register_zone_health_startup_listener(self) -> None:
        """Record when Home Assistant finished starting; zone-health alerts wait 10 minutes after that."""

        @callback
        def _mark_started(_event: Event | None = None) -> None:
            if self._zone_health_ha_started_at is not None:
                return
            self._zone_health_ha_started_at = dt_util.now()
            self._zone_health_earliest_alert_at = self._zone_health_ha_started_at + timedelta(
                minutes=10
            )

        if self.hass.state is CoreState.running:
            _mark_started()
        else:
            self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _mark_started)

    def _zone_health_post_startup_ready(self, now: datetime) -> bool:
        if self._zone_health_earliest_alert_at is None:
            return False
        return now >= self._zone_health_earliest_alert_at

    def _is_zone_health_enabled(self) -> bool:
        ts = self.config_manager.energy_config.get("tts_settings") or {}
        return _coerce_bool(ts.get("zone_health_check_enabled"), True)

    def _zone_health_ensure_store_loaded(self) -> dict:
        if self._zone_health_store_cache is None:
            self._zone_health_store_cache = load_store(zone_health_store_path(self.hass))
        return self._zone_health_store_cache

    def _zone_health_reload_store_from_disk(self) -> dict:
        self._zone_health_store_cache = load_store(zone_health_store_path(self.hass))
        return self._zone_health_store_cache

    def _zone_health_append_snapshots_blocking(
        self, now: datetime, history_days: int, person_keys: list[str]
    ) -> None:
        """Runs in executor: load JSON from disk, append snapshots, save (no shared cache mutation)."""
        path = zone_health_store_path(self.hass)
        data = load_store(path)
        persons = data.setdefault("persons", {})
        cutoff = now - timedelta(days=history_days)
        for pk in person_keys:
            pe = ensure_person_entry(persons, pk, now)
            prune_snapshots(pe, cutoff)
            states = self._zone_health_tracker_states_union(pk)
            append_snapshot(pe, states, now)
        save_store(path, data)

    def _build_zone_health_nearby_tokens(self) -> frozenset[str]:
        """Lowercase state strings that mean the Nearby zone (built once per recorder refresh).

        Includes each qualifying zone's object_id (e.g. brandons_nearby) because recorder
        device_tracker states often use the zone slug, not the literal ``nearby``.
        """
        tokens: set[str] = {"nearby"}
        for eid in self.hass.states.async_entity_ids("zone"):
            eid_l = eid.lower()
            object_id = eid.replace("zone.", "").lower()
            zs = self.hass.states.get(eid)
            if zs:
                fn = str(zs.attributes.get("friendly_name") or "").strip().lower()
                zone_slug = (fn if fn else eid.replace("zone.", "")).strip().lower()
            else:
                fn = ""
                zone_slug = object_id
            is_nearby_zone = eid == "zone.nearby" or fn == "nearby" or zone_slug == "nearby"
            if is_nearby_zone:
                tokens.add(zone_slug)
                tokens.add(eid_l)
                tokens.add(object_id)
                if fn:
                    tokens.add(fn)
        return frozenset(tokens)

    @staticmethod
    def _classify_zone_health_state_with_nearby_tokens(
        raw_state: str, nearby_tokens: frozenset[str]
    ) -> str | None:
        """Classify recorder/device_tracker state using precomputed Nearby zone tokens."""
        s = (raw_state or "").strip().lower()
        if s.startswith("at "):
            s = s[3:].strip()
        if s in ("unknown", "unavailable", ""):
            return None
        if s == "home":
            return "home"
        if s in ("not_home", "away"):
            return "not_home"
        if s in nearby_tokens:
            return "nearby"
        return "not_home" if s else None

    @staticmethod
    def _normalize_zone_health_state(state: str) -> str:
        """Normalize HA person / device_tracker states for zone-health listener callbacks."""
        s = (state or "").strip().lower()
        if s == "away":
            return "not_home"
        return s

    def _zone_health_tracker_states_union(self, person_key: str) -> set[str]:
        """Union of classified zone-health states from recorder (linked device_trackers only)."""
        out: set[str] = set()
        for bucket in (self._zone_health_tracker_recorder_cache.get(person_key) or {}).values():
            out |= set(bucket)
        return out

    def _get_person_linked_device_trackers(self, person_ent: str) -> list[str]:
        """Get device_tracker.* entities linked to a person (Person integration config first)."""
        return get_person_device_tracker_entity_ids(self.hass, person_ent)

    async def _async_refresh_zone_health_recorder_cache(self, force: bool = False) -> bool:
        """Fetch zone states from the recorder for each person's linked device_trackers only.

        Health uses HA recorder history on those trackers (not ``person.*``, not in-memory).
        Throttled to run at most every ``_zone_health_recorder_refresh_interval`` unless
        ``force`` is True (used by the dashboard "Refresh Status" action).

        Returns True if a full recorder pull ran (and JSON snapshots were appended).
        """
        now = dt_util.now()
        if not force and (
            self._zone_health_recorder_last_refresh
            and (now - self._zone_health_recorder_last_refresh) < self._zone_health_recorder_refresh_interval
        ):
            return False

        tts_settings = self.config_manager.energy_config.get("tts_settings") or {}
        history_days = int(tts_settings.get("zone_health_history_days", 3) or 3)
        start_time = now - timedelta(days=history_days)

        all_persons = self._distinct_presence_person_entity_ids()
        if not all_persons:
            self._zone_health_recorder_last_refresh = now
            return False

        try:
            from homeassistant.components.recorder.history import (
                get_significant_states_with_session,
                state_changes_during_period,
            )
            from homeassistant.components.recorder.util import session_scope
        except ImportError:
            _LOGGER.debug("Recorder not available for zone health history")
            self._zone_health_recorder_last_refresh = now
            return False

        nearby_tokens = self._build_zone_health_nearby_tokens()
        for person_ent in all_persons:
            person_key = str(person_ent).strip().lower()
            trackers = self._get_person_linked_device_trackers(person_key)
            entity_ids = list(dict.fromkeys([str(t).strip().lower() for t in trackers]))
            empty_meta = {
                "last_home": None,
                "last_nearby": None,
                "last_not_home": None,
            }
            if not entity_ids:
                self._zone_health_tracker_recorder_cache[person_key] = {}
                self._zone_health_recorder_cache[person_key] = set()
                self._zone_health_recorder_meta[person_key] = empty_meta
                _LOGGER.debug("Zone health recorder: %s has no linked device_trackers", person_key)
                continue

            _LOGGER.debug(
                "Zone health recorder: %s querying %d device_tracker entities",
                person_key,
                len(entity_ids),
            )
            states_union: set[str] = set()
            tracker_classified: dict[str, set[str]] = {}
            row_debug: dict[str, dict[str, int]] = {
                eid: {"state_changes": 0, "significant": 0} for eid in entity_ids
            }
            last_home_dt: datetime | None = None
            last_nearby_dt: datetime | None = None
            last_away_dt: datetime | None = None
            try:

                def _consume_state_row(st, source_eid: str) -> None:
                    nonlocal last_home_dt, last_nearby_dt, last_away_dt
                    raw = getattr(st, "state", None) or (
                        st.get("state") if isinstance(st, dict) else None
                    )
                    if not raw:
                        return
                    classified = self._classify_zone_health_state_with_nearby_tokens(
                        raw, nearby_tokens
                    )
                    if classified is None:
                        return
                    states_union.add(classified)
                    tracker_classified.setdefault(source_eid, set()).add(classified)
                    lc = getattr(st, "last_changed", None) or getattr(
                        st, "last_updated", None
                    )
                    if lc is None and isinstance(st, dict):
                        lc = st.get("last_changed") or st.get("last_updated")
                    if lc is not None:
                        if classified == "home":
                            if last_home_dt is None or lc > last_home_dt:
                                last_home_dt = lc
                        elif classified == "nearby":
                            if last_nearby_dt is None or lc > last_nearby_dt:
                                last_nearby_dt = lc
                        elif classified == "not_home":
                            if last_away_dt is None or lc > last_away_dt:
                                last_away_dt = lc

                # state_changes_during_period matches HA Activity (true state changes per entity).
                for eid in entity_ids:
                    eid_lower = eid.lower()
                    per_ent = state_changes_during_period(
                        self.hass,
                        start_time,
                        now,
                        entity_id=eid_lower,
                        no_attributes=True,
                        include_start_time_state=True,
                    )
                    rows = per_ent.get(eid_lower) or per_ent.get(eid) or []
                    row_debug[eid]["state_changes"] = len(rows)
                    for st in rows:
                        _consume_state_row(st, eid_lower)
                # Merge broader recorder rows so we still catch edge cases either API might miss.
                with session_scope(hass=self.hass, read_only=True) as session:
                    states_dict = get_significant_states_with_session(
                        self.hass,
                        session,
                        start_time,
                        now,
                        entity_ids,
                        None,
                        include_start_time_state=True,
                        significant_changes_only=False,
                        minimal_response=False,
                        no_attributes=False,
                    )
                for eid in entity_ids:
                    sig_list = states_dict.get(eid) or []
                    row_debug[eid]["significant"] = len(sig_list)
                    eid_lower = eid.lower()
                    for st in sig_list:
                        _consume_state_row(st, eid_lower)
            except Exception as e:
                _LOGGER.warning("Zone health recorder fetch failed for %s: %s", person_key, e)
            self._zone_health_tracker_recorder_cache[person_key] = {
                tid: set(states) for tid, states in tracker_classified.items()
            }
            self._zone_health_recorder_cache[person_key] = set(states_union)
            self._zone_health_recorder_meta[person_key] = {
                "last_home": last_home_dt.isoformat() if last_home_dt else None,
                "last_nearby": last_nearby_dt.isoformat() if last_nearby_dt else None,
                "last_not_home": last_away_dt.isoformat() if last_away_dt else None,
            }
            _LOGGER.debug(
                "Zone health recorder row counts for %s: %s",
                person_key,
                row_debug,
            )

        person_keys = [str(p).strip().lower() for p in all_persons]
        await self.hass.async_add_executor_job(
            self._zone_health_append_snapshots_blocking, now, history_days, person_keys
        )
        self._zone_health_store_cache = None

        self._zone_health_recorder_last_refresh = now
        _LOGGER.debug(
            "Zone health recorder cache refreshed for %d persons",
            len(all_persons),
        )
        return True

    def _zone_health_person_entry(self, person_key: str) -> dict | None:
        pk = str(person_key).strip().lower()
        data = self._zone_health_ensure_store_loaded()
        pe = (data.get("persons") or {}).get(pk)
        return pe if isinstance(pe, dict) else None

    def _person_zone_health_warmup_complete(
        self, person_key: str, now: datetime, history_days: int
    ) -> bool:
        pe = self._zone_health_person_entry(person_key)
        if pe is None:
            return False
        return warmup_complete(pe, now, history_days)

    def _is_person_zone_json_healthy(self, person_key: str) -> bool:
        """True if persisted JSON snapshots (rolling window) include home, nearby, and away."""
        if not self._get_person_linked_device_trackers(person_key):
            return False
        pe = self._zone_health_person_entry(person_key)
        if pe is None:
            return False
        union = union_states_from_snapshots(pe)
        return "home" in union and "nearby" in union and "not_home" in union

    def get_zone_health_status(self) -> dict:
        """Return zone health status for all configured persons (for WebSocket API)."""
        tts_settings = self.config_manager.energy_config.get("tts_settings") or {}
        history_days = int(tts_settings.get("zone_health_history_days", 3) or 3)
        if not self._is_zone_health_enabled():
            zone_entity_ids = set(self.hass.states.async_entity_ids("zone"))
            zone_home_ok = "zone.home" in zone_entity_ids
            zone_nearby_ok = "zone.nearby" in zone_entity_ids
            return {
                "zone_health_enabled": False,
                "history_days": history_days,
                "persons": [],
                "event_log": [],
                "recorder_refreshed_at": None,
                "required_zones": {
                    "zone_home": {
                        "entity_id": "zone.home",
                        "exists": zone_home_ok,
                        "setup_hint": (
                            ""
                            if zone_home_ok
                            else (
                                "Add or restore the default Home zone: Settings → Areas & zones → Zones. "
                                "The entity should be zone.home."
                            )
                        ),
                    },
                    "zone_nearby": {
                        "entity_id": "zone.nearby",
                        "exists": zone_nearby_ok,
                        "setup_hint": (
                            ""
                            if zone_nearby_ok
                            else (
                                "Create a zone named Nearby so the entity id is zone.nearby: "
                                "Settings → Areas & zones → Zones → Add zone. "
                                "See https://www.home-assistant.io/integrations/zone/"
                            )
                        ),
                    },
                },
            }
        now = dt_util.now()
        self._zone_health_reload_store_from_disk()
        all_persons = self._distinct_presence_person_entity_ids()
        persons_data = []
        for person_ent in all_persons:
            person_key = str(person_ent).strip().lower()
            ps = self.hass.states.get(person_key)
            current_state = (ps.state if ps else "unknown") or "unknown"
            name = self._get_person_friendly_name(person_key)
            trackers = self._get_person_linked_device_trackers(person_key)
            pe = self._zone_health_person_entry(person_key)
            warming_up = not (
                pe is not None and warmup_complete(pe, now, history_days)
            )
            warmup_complete_at = warmup_complete_at_iso(pe, history_days) if pe else None
            is_healthy = True if warming_up else self._is_person_zone_json_healthy(person_key)
            is_alerted = person_key in self._person_zone_health_alerted
            last_alert = self._person_zone_hourly_reminder_last.get(person_key)
            meta = self._zone_health_recorder_meta.get(person_key) or {}
            last_home = meta.get("last_home")
            last_nearby = meta.get("last_nearby")
            last_not_home = meta.get("last_not_home")
            all_states = self._zone_health_tracker_states_union(person_key)
            persons_data.append({
                "entity_id": person_key,
                "friendly_name": name,
                "device_trackers": trackers,
                "current_state": current_state,
                "is_healthy": is_healthy,
                "warming_up": warming_up,
                "warmup_complete_at": warmup_complete_at,
                "is_alerted": is_alerted,
                "last_home": last_home,
                "last_nearby": last_nearby,
                "last_not_home": last_not_home,
                "seen_home": "home" in all_states,
                "seen_nearby": "nearby" in all_states,
                "seen_away": "not_home" in all_states,
                "last_alert_time": last_alert.isoformat() if last_alert else None,
            })
        event_log = list(self._zone_health_event_log)
        zone_entity_ids = set(self.hass.states.async_entity_ids("zone"))
        zone_home_ok = "zone.home" in zone_entity_ids
        zone_nearby_ok = "zone.nearby" in zone_entity_ids
        return {
            "zone_health_enabled": True,
            "history_days": history_days,
            "persons": persons_data,
            "event_log": event_log,
            "recorder_refreshed_at": (
                self._zone_health_recorder_last_refresh.isoformat()
                if self._zone_health_recorder_last_refresh
                else None
            ),
            "required_zones": {
                "zone_home": {
                    "entity_id": "zone.home",
                    "exists": zone_home_ok,
                    "setup_hint": (
                        ""
                        if zone_home_ok
                        else (
                            "Add or restore the default Home zone: Settings → Areas & zones → Zones. "
                            "The entity should be zone.home."
                        )
                    ),
                },
                "zone_nearby": {
                    "entity_id": "zone.nearby",
                    "exists": zone_nearby_ok,
                    "setup_hint": (
                        ""
                        if zone_nearby_ok
                        else (
                            "Create a zone named Nearby so the entity id is zone.nearby: "
                            "Settings → Areas & zones → Zones → Add zone. "
                            "See https://www.home-assistant.io/integrations/zone/"
                        )
                    ),
                },
            },
        }

    async def async_force_zone_health_refresh(self) -> dict:
        """Re-query recorder for all persons + device_trackers, then run one health evaluation tick."""
        if not self._is_zone_health_enabled():
            return self.get_zone_health_status()
        await self._async_refresh_zone_health_recorder_cache(force=True)
        await self._async_tick_zone_health_check(dt_util.now())
        return self.get_zone_health_status()

    def _get_person_friendly_name(self, person_ent: str) -> str:
        """Get friendly name for a person entity."""
        person_key = str(person_ent).strip().lower()
        ps = self.hass.states.get(person_key)
        if ps and ps.attributes.get("friendly_name"):
            return str(ps.attributes["friendly_name"])
        return person_key.replace("person.", "").replace("_", " ").title()

    def _setup_zone_health_listeners(self) -> None:
        """Set up state change listeners for person entities to track zone health."""
        for unsub in self._person_zone_health_listener_unsub:
            unsub()
        self._person_zone_health_listener_unsub.clear()

        all_persons = self._distinct_presence_person_entity_ids()
        if not all_persons:
            return

        @callback
        def _on_person_state_change(event: Event) -> None:
            entity_id = str(event.data.get("entity_id", "")).strip().lower()
            new_state = event.data.get("new_state")
            if not new_state or not entity_id.startswith("person."):
                return
            state_val = (new_state.state or "").strip().lower()
            now = dt_util.now()
            norm = self._normalize_zone_health_state(state_val)
            self.hass.async_create_task(
                self._async_handle_zone_health_state_change(entity_id, norm, now)
            )

        unsub = async_track_state_change_event(
            self.hass, all_persons, _on_person_state_change
        )
        self._person_zone_health_listener_unsub.append(unsub)

        tracker_owner: dict[str, str] = {}
        for person_ent in all_persons:
            for tid in self._get_person_linked_device_trackers(person_ent):
                if tid.startswith("device_tracker.") and tid not in tracker_owner:
                    tracker_owner[tid] = person_ent

        @callback
        def _on_tracker_state_change(event: Event) -> None:
            entity_id = str(event.data.get("entity_id", "")).strip().lower()
            new_state = event.data.get("new_state")
            person_ent = tracker_owner.get(entity_id)
            if not person_ent or not new_state:
                return
            state_val = (new_state.state or "").strip().lower()
            now = dt_util.now()
            norm = self._normalize_zone_health_state(state_val)
            self.hass.async_create_task(
                self._async_handle_zone_health_state_change(person_ent, norm, now)
            )

        if tracker_owner:
            unsub_tr = async_track_state_change_event(
                self.hass, list(tracker_owner.keys()), _on_tracker_state_change
            )
            self._person_zone_health_listener_unsub.append(unsub_tr)

    async def _async_handle_zone_health_state_change(
        self, person_ent: str, new_state: str, now: datetime
    ) -> None:
        """Clear zone-health alert state when home, nearby, and away all appear in history."""
        person_key = str(person_ent).strip().lower()
        if not self._is_zone_health_enabled():
            return

        if not self._zone_health_post_startup_ready(now):
            return
        tts_settings = self.config_manager.energy_config.get("tts_settings") or {}
        history_days = int(tts_settings.get("zone_health_history_days", 3) or 3)
        pe = self._zone_health_person_entry(person_key)
        if pe is None or not warmup_complete(pe, now, history_days):
            return

        if person_key in self._person_zone_health_alerted and self._is_person_zone_json_healthy(
            person_key
        ):
            name = self._get_person_friendly_name(person_key)
            self._person_zone_health_alerted.discard(person_key)
            self._person_zone_hourly_reminder_last.pop(person_key, None)
            _LOGGER.info(
                "Zone health: %s tracking healthy (home, nearby, and away seen in window)",
                person_key,
            )
            self._log_zone_health_event(person_key, name, "recovered", "Home, nearby, and away all reporting")
            await self._async_speak_zone_health_tts(
                person_key,
                f"{name}, your location tracking looks good. Home, nearby, and away are all reporting.",
            )

    async def _async_speak_zone_health_tts(self, person_ent: str, message: str) -> None:
        """Speak a zone health TTS message to a room media player or default TTS player.

        Uses ``_zone_health_tts_lock`` to serialize TTS across all persons so messages
        do not overlap when multiple persons have zone health issues.
        """
        async with self._zone_health_tts_lock:
            await self._async_speak_zone_health_tts_inner(person_ent, message)

    async def _async_speak_zone_health_tts_inner(self, person_ent: str, message: str) -> None:
        """Inner TTS logic (called with lock held)."""
        tts_settings = self.config_manager.energy_config.get("tts_settings") or {}
        name = self._get_person_friendly_name(person_ent)
        tts_sent = False
        for room in self.config_manager.energy_config.get("rooms", []):
            if room.get("presence_person_entity") == person_ent:
                media_player = (room.get("media_player") or "").strip()
                if media_player.startswith("media_player."):
                    vol = float(room.get("volume", 0.7) or 0.7)
                    try:
                        await async_send_tts_or_queue(
                            self.hass,
                            media_player=media_player,
                            message=message,
                            language=tts_settings.get("language"),
                            volume=vol,
                            tts_settings=tts_settings,
                            room=room,
                        )
                        tts_sent = True
                        self._log_zone_health_event(person_ent, name, "tts_sent", message)
                    except Exception as e:
                        _LOGGER.warning("Zone health TTS failed: %s", e)
                        self._log_zone_health_event(person_ent, name, "tts_failed", str(e))
                    return
        default_mp = str(tts_settings.get("tts_default_media_player") or "").strip()
        if default_mp.startswith("media_player."):
            vol = float(tts_settings.get("volume", 0.7) or 0.7)
            try:
                await async_send_tts_or_queue(
                    self.hass,
                    media_player=default_mp,
                    message=message,
                    language=tts_settings.get("language"),
                    volume=vol,
                    tts_settings=tts_settings,
                    room=None,
                )
                tts_sent = True
                self._log_zone_health_event(person_ent, name, "tts_sent", message)
            except Exception as e:
                _LOGGER.warning("Zone health TTS (default player) failed: %s", e)
                self._log_zone_health_event(person_ent, name, "tts_failed", str(e))
        if not tts_sent and not default_mp:
            _LOGGER.warning("Zone health TTS skipped: no media player configured for %s", person_ent)
            self._log_zone_health_event(person_ent, name, "tts_skipped", "No media player configured")

    def _nearby_zone_exists(self) -> bool:
        """True if a zone named 'Nearby' (entity_id or friendly_name) exists."""
        for eid in self.hass.states.async_entity_ids("zone"):
            if eid == "zone.nearby":
                return True
            zs = self.hass.states.get(eid)
            if zs:
                fn = str(zs.attributes.get("friendly_name") or "").strip()
                if fn.lower() == "nearby":
                    return True
        return False

    async def _check_nearby_zone_notification(self) -> None:
        """Show or dismiss a persistent_notification about the missing Nearby zone."""
        notification_id = "smart_dashboards_nearby_zone_missing"
        exists = self._nearby_zone_exists()
        if exists:
            if self._nearby_zone_notification_shown:
                try:
                    await self.hass.services.async_call(
                        "persistent_notification",
                        "dismiss",
                        {"notification_id": notification_id},
                        blocking=False,
                    )
                except Exception:
                    pass
                self._nearby_zone_notification_shown = False
        else:
            if not self._nearby_zone_notification_shown:
                try:
                    await self.hass.services.async_call(
                        "persistent_notification",
                        "create",
                        {
                            "notification_id": notification_id,
                            "title": "Home Energy: Nearby zone not found",
                            "message": (
                                "Zone-based automations (e.g., AC presence) use a **Nearby** zone to detect when "
                                "someone is close to home but not inside. To enable this feature, create a zone "
                                "named **Nearby** with a radius of approximately **1 mile (1609 m)** centered on your home.\n\n"
                                "Go to **Settings → Areas & zones → Zones** → **Add Zone**, set the name to `Nearby`, "
                                "place the marker on your home address, and set the radius to ~1609 m.\n\n"
                                "This notification will auto-dismiss once the zone is created."
                            ),
                        },
                        blocking=False,
                    )
                    self._nearby_zone_notification_shown = True
                except Exception as e:
                    _LOGGER.warning("Failed to create Nearby zone persistent notification: %s", e)

    async def _async_tick_zone_health_check(self, now: datetime) -> None:
        """Detect unhealthy zone tracking; repeat TTS/push spaced by zone_health_reminder_hours."""
        if not self._is_zone_health_enabled():
            return

        # Check Nearby zone existence once per pass (only when zone health is enabled)
        await self._check_nearby_zone_notification()

        tts_settings = self.config_manager.energy_config.get("tts_settings") or {}

        # Refresh recorder-backed history cache (throttled internally); append JSON snapshots when it runs.
        await self._async_refresh_zone_health_recorder_cache()

        reminder_hours = int(tts_settings.get("zone_health_reminder_hours", 1) or 1)
        reminder_seconds = reminder_hours * 3600
        history_days = int(tts_settings.get("zone_health_history_days", 3) or 3)

        post_ready = self._zone_health_post_startup_ready(now)
        all_persons = self._distinct_presence_person_entity_ids()
        for person_ent in all_persons:
            pk = str(person_ent).strip().lower()
            if not self._person_zone_health_warmup_complete(pk, now, history_days):
                continue
            if self._is_person_zone_json_healthy(pk):
                continue
            if not post_ready:
                continue
            name = self._get_person_friendly_name(pk)
            if pk not in self._person_zone_health_alerted:
                self._person_zone_health_alerted.add(pk)
                self._person_zone_hourly_reminder_last[pk] = now
                _LOGGER.warning(
                    "Zone health: %s has not shown home, nearby, and away in %d days (JSON window)",
                    pk,
                    history_days,
                )
                first_msg_template = str(
                    tts_settings.get(
                        "zone_health_notification_msg",
                        "Hi {name}, your Home Assistant Companion app location doesn't appear to be set up correctly.",
                    )
                    or "Hi {name}, your zone tracking setup needs attention."
                )
                first_msg = first_msg_template.replace("{name}", name)
                await self._async_speak_zone_health_tts(pk, first_msg)
                await self._send_zone_health_push_notification(pk, name)
            else:
                last_reminder = self._person_zone_hourly_reminder_last.get(pk)
                if not last_reminder or (now - last_reminder).total_seconds() >= reminder_seconds:
                    self._person_zone_hourly_reminder_last[pk] = now
                    msg_template = str(
                        tts_settings.get(
                            "zone_health_reminder_tts_msg",
                            "{name}, your zone-based location setup needs attention. Please check your Companion app settings.",
                        )
                        or "{name}, your zone-based location setup needs attention."
                    )
                    msg = msg_template.replace("{name}", name)
                    await self._async_speak_zone_health_tts(pk, msg)
                    await self._send_zone_health_push_notification(pk, name)

    def _log_zone_health_event(
        self, person_ent: str, name: str, event_type: str, message: str = ""
    ) -> None:
        """Log a zone health event for UI display."""
        from homeassistant.util import dt as dt_util
        self._zone_health_event_log.append({
            "ts": dt_util.now().isoformat(),
            "person_entity": person_ent,
            "person_name": name,
            "event": event_type,
            "message": message,
        })

    async def _send_zone_health_push_notification(self, person_ent: str, name: str) -> None:
        """Send push notification about zone tracking not working."""
        tts_settings = self.config_manager.energy_config.get("tts_settings") or {}
        title = "Zone Tracking Setup Issue"
        msg_template = str(
            tts_settings.get(
                "zone_health_notification_msg",
                "Hi {name}, your Home Assistant Companion app location doesn't appear to be set up correctly. Zone-based presence isn't working.",
            )
            or "Hi {name}, your zone tracking setup needs attention."
        )
        message = msg_template.replace("{name}", name)
        sent = await self._async_send_mobile_notification_to_person(
            person_ent, title, message
        )
        if sent:
            self._log_zone_health_event(person_ent, name, "push_sent", message)
        else:
            self._log_zone_health_event(
                person_ent,
                name,
                "push_failed",
                "No mobile_app notify target resolved",
            )

    def _heater_door_window_blocks(self, outlet: dict) -> str | None:
        """Return 'door' or 'window' if sensor is open, else None.

        Uses :meth:`_contact_sensor_state_is_open` so both HA-canonical ``on``
        and MQTT-style ``open`` values are accepted (audit BUG 8: previously
        only ``on`` was matched, so a door/window reporting ``open`` would not
        block the heater). When both are open, 'door' is reported first so the
        user knows to close it.
        """
        door_ent = str(outlet.get("heater_door_sensor_entity") or "").strip()
        window_ent = str(outlet.get("heater_window_sensor_entity") or "").strip()
        if door_ent.startswith("binary_sensor."):
            ds = self.hass.states.get(door_ent)
            if ds and self._contact_sensor_state_is_open(ds.state):
                return "door"
        if window_ent.startswith("binary_sensor."):
            ws = self.hass.states.get(window_ent)
            if ws and self._contact_sensor_state_is_open(ws.state):
                return "window"
        return None

    async def _announce_heater_blocked(self, room: dict, room_name: str, blocker: str) -> None:
        """TTS and push notification when heater blocked by open door/window."""
        tts_settings = self.config_manager.energy_config.get("tts_settings") or {}
        prefix = tts_settings.get("prefix", DEFAULT_TTS_PREFIX)
        msg = f"{prefix} {room_name} heater cannot be turned on unless the {blocker} is closed."

        await self._async_speak_appliance_automation_tts(room, msg)

        for person_ent in self._distinct_presence_person_entity_ids():
            await self._async_send_mobile_notification_to_person(
                person_ent,
                f"{room_name} Heater Blocked",
                f"Heater cannot turn on—the {blocker} is open.",
            )

    def _enforcement_cycle_enter(self, room_id: str) -> None:
        self._enforcement_power_cycle_depth[room_id] = (
            self._enforcement_power_cycle_depth.get(room_id, 0) + 1
        )

    def _enforcement_cycle_exit(self, room_id: str) -> None:
        c = self._enforcement_power_cycle_depth.get(room_id, 0) - 1
        if c <= 0:
            self._enforcement_power_cycle_depth.pop(room_id, None)
        else:
            self._enforcement_power_cycle_depth[room_id] = c

    def _room_in_enforcement_power_cycle(self, room_id: str) -> bool:
        return self._enforcement_power_cycle_depth.get(room_id, 0) > 0

    def _tts_line_enabled(self, tts: dict, line: str) -> bool:
        """Per-message TTS toggle from tts_settings (default on). Vent/heater use legacy keys."""
        if line == "vent_automation":
            return bool(tts.get("vent_automation_tts_enabled"))
        if line == "heater_automation":
            return bool(tts.get("heater_automation_tts_enabled"))
        per_key = f"{line}_tts_enabled"
        if per_key in tts and tts[per_key] is not None:
            return tts[per_key] is not False
        # Door/window/presence/battery: honor section master toggles when per-line key absent
        if line.startswith("door_"):
            return tts.get("door_tts_enabled", True) is not False
        if line.startswith("window_"):
            return tts.get("window_tts_enabled", True) is not False
        if line.startswith("presence_"):
            return tts.get("presence_tts_enabled", True) is not False
        if line.startswith("battery_"):
            return tts.get("battery_tts_enabled", True) is not False
        return tts.get(per_key, True) is not False

    @staticmethod
    def _contact_sensor_state_is_open(state: str | None) -> bool:
        """True if contact sensor state means open (on/open); supports HA and MQTT-style values.

        Delegates to the canonical :func:`door_window.contact_is_open` so the
        open-state check has one source of truth across the integration and the
        frontend (audit BUG 8).
        """
        from .door_window import contact_is_open
        return contact_is_open(state)

    @staticmethod
    def _budget_boost_period_label(weekdays: list) -> str:
        """Phrase for TTS: weekend only when Sat+Sun; else 'on Monday and Tuesday' style."""
        names = [
            "Monday",
            "Tuesday",
            "Wednesday",
            "Thursday",
            "Friday",
            "Saturday",
            "Sunday",
        ]
        try:
            wk = sorted({int(d) for d in weekdays if 0 <= int(d) <= 6})
        except (TypeError, ValueError):
            wk = []
        if not wk:
            return "on selected days"
        if set(wk) == {5, 6}:
            return "for the weekend"
        if len(wk) == 1:
            return f"on {names[wk[0]]}"
        if len(wk) == 2:
            return f"on {names[wk[0]]} and {names[wk[1]]}"
        return "on " + ", ".join(names[d] for d in wk[:-1]) + f", and {names[wk[-1]]}"

    def _any_room_budget_boost_active_today(
        self, now: datetime, tts_settings: dict
    ) -> bool:
        """True if at least one room with a positive kWh budget uses boost and today is a boost day."""
        if not tts_settings.get("budget_boost_enabled"):
            return False
        rooms = self.config_manager.energy_config.get("rooms") or []
        if not rooms:
            mult = float(tts_settings.get("budget_boost_multiplier") or 1)
            if mult <= 1:
                return False
            return ConfigManager._is_budget_boost_day(now, tts_settings, None)
        for room in rooms:
            if room.get("kwh_budget_use_boost", True) is False:
                continue
            if float(room.get("kwh_budget", 5) or 0) <= 0:
                continue
            if ConfigManager._is_budget_boost_day(now, tts_settings, room):
                return True
        return False

    def _merged_boost_weekdays_for_scheduled_tts(self, tts_settings: dict) -> list[int]:
        """Union of per-room / global boost weekdays for scheduled announcement copy."""
        seen: set[int] = set()
        for room in self.config_manager.energy_config.get("rooms") or []:
            if room.get("kwh_budget_use_boost", True) is False:
                continue
            if float(room.get("kwh_budget", 5) or 0) <= 0:
                continue
            for d in resolve_budget_boost_weekdays(room, tts_settings):
                seen.add(int(d))
        if seen:
            return sorted(seen)
        return resolve_budget_boost_weekdays(None, tts_settings)

    def _effective_kwh_budget(
        self,
        base: float,
        now: datetime,
        tts_settings: dict,
        *,
        use_room_boost: bool = True,
        room: dict | None = None,
    ) -> float:
        return self.config_manager.effective_kwh_budget_for_moment(
            base,
            now,
            tts_settings,
            use_room_boost=use_room_boost,
            room=room,
        )

    @staticmethod
    def _budget_multiplier_tts_str(mult: float) -> str:
        if mult == int(mult):
            return str(int(mult))
        return str(mult).rstrip("0").rstrip(".")

    def _budget_boost_slots_path(self) -> str:
        return self.config_manager._data_path("budget_boost_slots.json")

    async def _async_load_budget_boost_slots(self) -> None:
        path = self._budget_boost_slots_path()
        try:
            def _read() -> dict | None:
                if not os.path.isfile(path):
                    return None
                with open(path, encoding="utf-8") as f:
                    return json.load(f)

            data = await self.hass.async_add_executor_job(_read)
            if isinstance(data, dict):
                self._budget_boost_slots_fired = {
                    str(k): [int(x) for x in v]
                    for k, v in data.items()
                    if isinstance(v, list)
                }
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as err:
            _LOGGER.debug("Budget boost slots load skipped: %s", err)

    async def _async_save_budget_boost_slots(self) -> None:
        path = self._budget_boost_slots_path()

        def _write() -> None:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._budget_boost_slots_fired, f, indent=2)

        try:
            await self.hass.async_add_executor_job(_write)
        except OSError as err:
            _LOGGER.warning("Budget boost slots save failed: %s", err)

    @staticmethod
    def _parse_hhmm_to_minutes(s: str | None, default_h: int, default_m: int) -> int:
        if not s:
            return default_h * 60 + default_m
        try:
            parts = str(s).strip().replace(".", ":").split(":")
            h = int(parts[0])
            mi = int(parts[1]) if len(parts) > 1 else 0
            if 0 <= h <= 23 and 0 <= mi <= 59:
                return h * 60 + mi
        except (ValueError, IndexError, TypeError):
            pass
        return default_h * 60 + default_m

    @staticmethod
    def _iter_budget_boost_slot_minutes(
        t0: int, t1: int, repeat_min: int, minute_offset: int
    ) -> list[int]:
        """Slot start times as minutes from midnight, inclusive window [t0, t1]."""
        if t1 < t0:
            t0, t1 = t1, t0
        repeat_min = max(15, repeat_min)
        mo = max(0, min(59, minute_offset))
        slots: list[int] = []
        t = t0
        while t % 60 != mo and t <= t1:
            t += 1
        while t <= t1:
            slots.append(t)
            t += repeat_min
        return slots

    async def _maybe_fire_budget_boost_scheduled(
        self, now: datetime, today: str, tts_settings: dict
    ) -> None:
        """On boost days, TTS at each repeat slot inside the configured time window."""
        if not self._any_room_budget_boost_active_today(now, tts_settings):
            return
        mp = (
            str(tts_settings.get("tts_default_media_player") or "").strip()
            or str(tts_settings.get("budget_boost_announce_media_player") or "").strip()
        )
        if not mp:
            return
        if not self._tts_line_enabled(tts_settings, "budget_boost_scheduled"):
            return
        start_s = str(tts_settings.get("budget_boost_window_start") or "").strip() or str(
            tts_settings.get("budget_boost_announce_time") or "09:00"
        )
        end_s = str(tts_settings.get("budget_boost_window_end") or "").strip() or "21:00"
        t0 = self._parse_hhmm_to_minutes(start_s, 9, 0)
        t1 = self._parse_hhmm_to_minutes(end_s, 21, 0)
        repeat_min = int(tts_settings.get("budget_boost_repeat_minutes") or 120)
        mo = int(tts_settings.get("budget_boost_minute_offset") or 0)
        slot_minutes = self._iter_budget_boost_slot_minutes(t0, t1, repeat_min, mo)
        now_min = now.hour * 60 + now.minute
        fired = set(self._budget_boost_slots_fired.get(today, []))
        first_run_today = self._budget_boost_scheduled_fired_date != today
        if first_run_today:
            for sm in slot_minutes:
                if sm < now_min:
                    fired.add(sm)
            self._budget_boost_slots_fired[today] = sorted(fired)
            await self._async_save_budget_boost_slots()
            self._budget_boost_scheduled_fired_date = today
        tmpl = (tts_settings.get("budget_boost_scheduled_msg") or "").strip() or DEFAULT_BUDGET_BOOST_SCHEDULED_MSG
        prefix = tts_settings.get("prefix", DEFAULT_TTS_PREFIX)
        weekdays = self._merged_boost_weekdays_for_scheduled_tts(tts_settings)
        period = self._budget_boost_period_label(weekdays)
        mult = float(tts_settings.get("budget_boost_multiplier") or 2)
        mult_s = self._budget_multiplier_tts_str(max(1.0, min(5.0, mult)))
        vol = float(tts_settings.get("volume", 0.7) or 0.7)
        changed = False
        for sm in slot_minutes:
            if sm > now_min:
                continue
            if sm in fired:
                continue
            if sm == now_min:
                pass
            try:
                message = tmpl.format(
                    prefix=prefix,
                    period_label=period,
                    budget_multiplier=mult_s,
                )
            except (KeyError, ValueError) as e:
                _LOGGER.warning("Budget boost scheduled message format failed: %s", e)
                continue
            try:
                await async_send_tts_or_queue(
                    self.hass,
                    media_player=mp,
                    message=message,
                    language=tts_settings.get("language"),
                    volume=vol,
                    tts_settings=tts_settings,
                    room=None,
                )
            except Exception as e:
                _LOGGER.error("Budget boost scheduled TTS failed: %s", e)
                continue
            fired.add(sm)
            changed = True
        if changed:
            self._budget_boost_slots_fired[today] = sorted(fired)
            await self._async_save_budget_boost_slots()
        self._budget_boost_scheduled_fired_date = today

    def _get_power_entity_ids(self) -> list[str]:
        """Collect all power entity IDs we track for daily energy."""
        entity_ids = []
        for room in self.config_manager.energy_config.get("rooms", []):
            room_id = room.get("id", room["name"].lower().replace(" ", "_"))
            for outlet in room.get("outlets", []):
                if outlet.get("type") == "light":
                    if outlet.get("power_source") == "sensor":
                        pe = outlet.get("power_sensor_entity")
                        if pe:
                            entity_ids.append(pe)
                    continue
                if outlet.get("type") in ("vent", "wall_heater"):
                    if outlet.get("power_source") == "sensor":
                        pe = outlet.get("power_sensor_entity")
                        if pe:
                            entity_ids.append(pe)
                    continue
                if outlet.get("plug1_entity"):
                    entity_ids.append(outlet["plug1_entity"])
                if outlet.get("plug2_entity"):
                    entity_ids.append(outlet["plug2_entity"])
        return list(dict.fromkeys(entity_ids))  # Dedupe preserving order

    def _switch_entity_is_on(self, entity_id: str | None) -> bool:
        if not entity_id or not str(entity_id).startswith("switch."):
            return False
        st = self.hass.states.get(entity_id)
        return bool(st and (st.state or "").lower() == "on")

    @staticmethod
    def _is_switch_entity_id(entity_id: str | None) -> bool:
        return bool(entity_id and str(entity_id).startswith("switch."))

    @staticmethod
    def _is_appliance_control_entity(entity_id: str | None) -> bool:
        """Vent/heater card may use switch.* or fan.* as the controlled load."""
        if not entity_id:
            return False
        s = str(entity_id).strip()
        return s.startswith("switch.") or s.startswith("fan.")

    @staticmethod
    def _appliance_automation_key(room_id: str, outlet: dict) -> str:
        slug = (outlet.get("name") or "device").lower().replace(" ", "_")
        return f"{room_id}|{slug}"

    def _binary_presence_positive(self, entity_id: str | None) -> bool:
        eid = str(entity_id or "").strip()
        if not eid:
            return False
        st = self.hass.states.get(eid)
        if not st or st.state in ("unknown", "unavailable", ""):
            return False
        raw = (st.state or "").lower().strip()
        positives = frozenset(
            (
                "on",
                "true",
                "1",
                "yes",
                "detected",
                "occupied",
                "motion",
                "active",
                "present",
                "home",
            )
        )
        if raw in positives:
            return True
        if eid.startswith("input_boolean."):
            return raw == "on"
        dc = str(st.attributes.get("device_class") or "").lower()
        if dc in ("occupancy", "motion", "presence", "sound", "vibration", "moisture"):
            return raw == "on"
        return False

    def _appliance_entity_is_on(self, entity_id: str | None) -> bool:
        """True if switch or fan entity reads as running (for vent/heater automation)."""
        if not entity_id:
            return False
        eid = str(entity_id).strip()
        st = self.hass.states.get(eid)
        if not st:
            return False
        raw = (st.state or "").lower()
        if eid.startswith("switch."):
            return raw == "on"
        if eid.startswith("fan."):
            return raw in ("on", "true", "1")
        return False

    def _parse_temperature_sensor(self, entity_id: str | None) -> float | None:
        st = self.hass.states.get(entity_id or "")
        if not st or st.state in ("unknown", "unavailable", ""):
            return None
        try:
            return float(st.state)
        except (TypeError, ValueError):
            return None

    async def _get_weather_forecast(self, weather_entity: str) -> list[dict]:
        """Call weather.get_forecasts service and return hourly forecast."""
        if not weather_entity or not weather_entity.startswith("weather."):
            return []
        try:
            result = await self.hass.services.async_call(
                "weather",
                "get_forecasts",
                {"entity_id": weather_entity, "type": "hourly"},
                blocking=True,
                return_response=True,
            )
            if result and isinstance(result, dict):
                forecasts = result.get(weather_entity, {}).get("forecast", [])
                return forecasts if isinstance(forecasts, list) else []
            return []
        except Exception as e:
            _LOGGER.debug("Failed to get weather forecast from %s: %s", weather_entity, e)
            return []

    async def _get_outdoor_and_forecast(
        self, weather_entity: str
    ) -> tuple[float | None, list[dict]]:
        """Get outdoor temperature and forecast from weather or sensor entity."""
        if not weather_entity:
            return None, []

        outdoor_temp: float | None = None
        forecast: list[dict] = []

        if weather_entity.startswith("weather."):
            st = self.hass.states.get(weather_entity)
            if st and st.state not in ("unknown", "unavailable", ""):
                try:
                    outdoor_temp = float(st.attributes.get("temperature", 0))
                except (TypeError, ValueError):
                    pass
            forecast = await self._get_weather_forecast(weather_entity)
        elif weather_entity.startswith("sensor."):
            outdoor_temp = self._parse_temperature_sensor(weather_entity)

        return outdoor_temp, forecast

    def _forecast_needs_preheat(
        self,
        forecast: list[dict],
        outdoor_temp: float | None,
        indoor_temp: float | None,
        comfort: float,
        preheat_mins: int,
    ) -> bool:
        """Check if forecast shows cold spell requiring pre-heating."""
        if not forecast or preheat_mins <= 0 or indoor_temp is None:
            return False
        if indoor_temp >= comfort:
            return False

        now = dt_util.utcnow()
        preheat_window = now + timedelta(minutes=preheat_mins)

        for entry in forecast:
            dt_str = entry.get("datetime")
            if not dt_str:
                continue
            try:
                entry_time = dt_util.parse_datetime(dt_str)
                if not entry_time:
                    continue
                if entry_time > preheat_window:
                    break
                forecast_temp = float(entry.get("temperature", 100))
                if forecast_temp < comfort - 5:
                    return True
            except (TypeError, ValueError):
                continue
        return False

    def _get_heater_smart_state(self, key: str) -> dict:
        """Get or initialize smart heater state for a heater."""
        if key not in self._heater_smart_state:
            self._heater_smart_state[key] = {
                "smart_mode": "idle",
                "heating_since": None,
                "duty_pause_until": None,
                "power_pause_since": None,
                "temp_history": deque(maxlen=120),
                "heating_rate": 0.0,
                "cooling_rate": 0.0,
                "last_rate_calc": None,
            }
        return self._heater_smart_state[key]

    def _update_temp_history(
        self, key: str, now: datetime, temp: float | None, heater_on: bool
    ) -> None:
        """Add temperature sample to history for thermal rate learning."""
        if temp is None:
            return
        smart_st = self._get_heater_smart_state(key)
        history = smart_st["temp_history"]
        history.append((now, temp, heater_on))

    def _calculate_thermal_rates(self, key: str) -> tuple[float, float]:
        """Calculate heating and cooling rates from temperature history.
        
        Returns (heating_rate, cooling_rate) in degrees per minute.
        Positive values for both (heating goes up, cooling goes down).
        """
        smart_st = self._get_heater_smart_state(key)
        history = smart_st["temp_history"]
        
        if len(history) < 10:
            return smart_st.get("heating_rate", 0.0), smart_st.get("cooling_rate", 0.0)

        now = dt_util.utcnow()
        last_calc = smart_st.get("last_rate_calc")
        if last_calc and (now - last_calc).total_seconds() < 60:
            return smart_st.get("heating_rate", 0.0), smart_st.get("cooling_rate", 0.0)

        heating_deltas: list[float] = []
        cooling_deltas: list[float] = []

        history_list = list(history)
        for i in range(1, len(history_list)):
            prev_time, prev_temp, prev_on = history_list[i - 1]
            curr_time, curr_temp, curr_on = history_list[i]
            
            elapsed_mins = (curr_time - prev_time).total_seconds() / 60.0
            if elapsed_mins <= 0 or elapsed_mins > 5:
                continue
            
            temp_delta = curr_temp - prev_temp
            rate = temp_delta / elapsed_mins
            
            if prev_on and curr_on and temp_delta > 0:
                heating_deltas.append(rate)
            elif not prev_on and not curr_on and temp_delta < 0:
                cooling_deltas.append(abs(rate))

        if heating_deltas:
            new_heating = sum(heating_deltas) / len(heating_deltas)
            old_heating = smart_st.get("heating_rate", 0.0)
            smart_st["heating_rate"] = old_heating * 0.7 + new_heating * 0.3 if old_heating else new_heating

        if cooling_deltas:
            new_cooling = sum(cooling_deltas) / len(cooling_deltas)
            old_cooling = smart_st.get("cooling_rate", 0.0)
            smart_st["cooling_rate"] = old_cooling * 0.7 + new_cooling * 0.3 if old_cooling else new_cooling

        smart_st["last_rate_calc"] = now
        return smart_st.get("heating_rate", 0.0), smart_st.get("cooling_rate", 0.0)

    def _estimate_time_to_comfort(
        self, current_temp: float, comfort: float, heating_rate: float
    ) -> float | None:
        """Estimate minutes to reach comfort temp based on heating rate."""
        if heating_rate <= 0 or current_temp >= comfort:
            return None
        temp_diff = comfort - current_temp
        return temp_diff / heating_rate

    async def _async_switch_set(self, entity_id: str, turn_on: bool) -> None:
        self._mark_switch_internal(entity_id)
        try:
            await self.hass.services.async_call(
                "switch",
                "turn_on" if turn_on else "turn_off",
                {"entity_id": entity_id},
                blocking=True,
            )
        except Exception as e:
            _LOGGER.warning(
                "Switch %s %s failed: %s",
                entity_id,
                "on" if turn_on else "off",
                e,
            )

    async def _async_appliance_power_set(self, entity_id: str, turn_on: bool) -> None:
        """Turn vent/heater load on or off (switch or fan domain)."""
        eid = str(entity_id or "").strip()
        if eid.startswith("switch."):
            domain = "switch"
            self._mark_switch_internal(eid)
        elif eid.startswith("fan."):
            domain = "fan"
        else:
            _LOGGER.warning(
                "Appliance control entity %s must be switch.* or fan.*",
                eid,
            )
            return
        try:
            await self.hass.services.async_call(
                domain,
                "turn_on" if turn_on else "turn_off",
                {"entity_id": eid},
                blocking=True,
            )
        except Exception as e:
            _LOGGER.warning(
                "%s %s %s failed: %s",
                domain,
                eid,
                "on" if turn_on else "off",
                e,
            )

    def _mark_switch_internal(self, entity_id: str) -> None:
        """Mark a switch as toggled by this integration (suppress external auto notify)."""
        eid = str(entity_id or "").strip()
        if not eid:
            return
        self._integration_internal_switch_ids.add(eid)

        async def _clear() -> None:
            await asyncio.sleep(3.0)
            self._integration_internal_switch_ids.discard(eid)

        self.hass.async_create_task(_clear())

    async def _async_wall_heater_set_switch(self, entity_id: str, turn_on: bool) -> None:
        self._mark_switch_internal(entity_id)
        await self._async_appliance_power_set(entity_id, turn_on)

    async def _async_speak_appliance_automation_tts(
        self, room: dict, message: str
    ) -> None:
        mp = (room.get("media_player") or "").strip()
        if not mp.startswith("media_player."):
            return
        tts_settings = self.config_manager.energy_config.get("tts_settings") or {}
        vol = float(room.get("volume", 0.7) or 0.7)
        try:
            await async_send_tts_or_queue(
                self.hass,
                media_player=mp,
                message=message,
                language=tts_settings.get("language"),
                volume=vol,
                tts_settings=tts_settings,
                room=room,
            )
        except Exception as e:
            _LOGGER.warning("Appliance automation TTS failed: %s", e)

    async def _send_notification_to_room_person(
        self,
        room: dict,
        notification_type: str,
        template_vars: dict | None = None,
        fallback_title: str = "",
        fallback_message: str = "",
        *,
        integration_auto: bool = False,
    ) -> None:
        """Send HA notification to person assigned to room using configured templates."""
        tts_settings = self.config_manager.energy_config.get("tts_settings") or {}
        if integration_auto:
            if not tts_settings.get("notify_integration_auto", True):
                _LOGGER.debug(
                    "Notification blocked: notify_integration_auto is disabled for type=%s",
                    notification_type,
                )
                return
        else:
            if not tts_settings.get("notifications_enabled"):
                _LOGGER.debug(
                    "Notification blocked: notifications_enabled is disabled for type=%s",
                    notification_type,
                )
                return
        enable_key = self._notification_enable_key(notification_type)
        enable_value = tts_settings.get(enable_key, True)
        _LOGGER.debug(
            "Notification check: type=%s, enable_key=%s, value=%s",
            notification_type,
            enable_key,
            enable_value,
        )
        if not enable_value:
            _LOGGER.debug(
                "Notification blocked: %s is disabled (value=%s)",
                enable_key,
                enable_value,
            )
            return
        person_ent = room.get("presence_person_entity")
        if not person_ent:
            return
        person_state = self.hass.states.get(person_ent)
        if not person_state:
            return
        person_name = (
            person_state.attributes.get("friendly_name")
            or person_ent.replace("person.", "").replace("_", " ").title()
        )
        prefix = tts_settings.get("prefix", DEFAULT_TTS_PREFIX)
        notification_title = str(
            tts_settings.get("notification_title") or DEFAULT_NOTIFICATION_TITLE
        ).strip() or DEFAULT_NOTIFICATION_TITLE

        title_key, msg_key = self._notification_template_keys(notification_type)
        title_template = (
            tts_settings.get(title_key)
            or fallback_title
            or "{notification_title} Notification"
        )
        msg_template = tts_settings.get(msg_key) or fallback_message or "Notification from Smart Dashboards."

        vars_fmt = {
            "prefix": prefix,
            "notification_title": notification_title,
            **(template_vars or {}),
            "person_name": person_name,
            "person": person_name,
        }
        try:
            title = title_template.format(**vars_fmt)
            message = msg_template.format(**vars_fmt)
        except (KeyError, ValueError) as e:
            _LOGGER.warning("Notification template format failed: %s", e)
            title = (
                f"{notification_title} {fallback_title}".strip()
                if fallback_title
                else f"{notification_title} Notification"
            )
            message = fallback_message or "Notification from Smart Dashboards."

        await self._async_send_mobile_notification_to_person(person_ent, title, message)

    async def _async_send_mobile_notification_to_person(
        self, person_ent: str, title: str, message: str
    ) -> bool:
        """Deliver a formatted push to one person's mobile_app notify target.

        Uses inline ``resolve_notify_target`` + service calls (person id not lowercased before resolve).
        Dashboard test notifications use ``async_send_notify_push`` instead.
        """
        target = resolve_notify_target(self.hass, person_ent)
        if not target:
            _LOGGER.warning(
                "Cannot send push to %s: no mobile_app notify target resolved. "
                "Ensure a phone is linked under Settings → People and the Companion app is registered.",
                person_ent,
            )
            return False

        try:
            if target.mode == "legacy_service" and target.service_name:
                await self.hass.services.async_call(
                    "notify",
                    target.service_name,
                    {"title": title, "message": message},
                    blocking=False,
                )
                _LOGGER.debug(
                    "Sent notification via %s: %s - %s", target.service_name, title, message
                )
            elif target.mode == "notify_send" and target.entity_id:
                if self.hass.services.has_service("notify", "send_message"):
                    await self.hass.services.async_call(
                        "notify",
                        "send_message",
                        {"entity_id": target.entity_id, "title": title, "message": message},
                        blocking=False,
                    )
                elif self.hass.services.has_service("notify", "send"):
                    await self.hass.services.async_call(
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
                    _LOGGER.warning(
                        "Cannot send push: neither notify.send_message nor notify.send for %s",
                        target.entity_id,
                    )
                    return False
                _LOGGER.debug(
                    "Sent notification via notify entity %s: %s - %s",
                    target.entity_id,
                    title,
                    message,
                )
            else:
                _LOGGER.warning(
                    "Unknown notify target mode for %s: %s", person_ent, target
                )
                return False
            return True
        except Exception as e:
            _LOGGER.warning(
                "Failed to send notification to %s (target=%s): %s", person_ent, target, e
            )
            return False

    async def _send_notification_broadcast(
        self,
        notification_type: str,
        template_vars: dict | None,
        fallback_title: str,
        fallback_message: str,
    ) -> None:
        """Send the same push to every person assigned on any room (universal alerts)."""
        tts_settings = self.config_manager.energy_config.get("tts_settings") or {}
        if not tts_settings.get("notifications_enabled"):
            return
        enable_key = self._notification_enable_key(notification_type)
        if not tts_settings.get(enable_key, True):
            return
        recipients = self._distinct_presence_person_entity_ids()
        if not recipients:
            _LOGGER.debug(
                "No presence persons configured on any room; skip %s broadcast",
                notification_type,
            )
            return
        prefix = tts_settings.get("prefix", DEFAULT_TTS_PREFIX)
        notification_title = str(
            tts_settings.get("notification_title") or DEFAULT_NOTIFICATION_TITLE
        ).strip() or DEFAULT_NOTIFICATION_TITLE
        title_key, msg_key = self._notification_template_keys(notification_type)
        title_template = (
            tts_settings.get(title_key)
            or fallback_title
            or "{notification_title} Notification"
        )
        msg_template = (
            tts_settings.get(msg_key)
            or fallback_message
            or DEFAULT_NOTIFY_MANUAL_TOGGLE_MSG
        )
        vars_fmt = {
            "prefix": prefix,
            "notification_title": notification_title,
            **(template_vars or {}),
        }
        try:
            title = title_template.format(**vars_fmt)
            message = msg_template.format(**vars_fmt)
        except (KeyError, ValueError) as e:
            _LOGGER.warning("Broadcast notification template format failed: %s", e)
            title = (
                f"{notification_title} {fallback_title}".strip()
                if fallback_title
                else f"{notification_title} Notification"
            )
            message = fallback_message or "Notification from Smart Dashboards."
        for person_ent in recipients:
            await self._async_send_mobile_notification_to_person(
                person_ent, title, message
            )

    def _find_outlet_by_switch(self, room: dict, switch_entity: str) -> dict | None:
        """Find outlet config in room that uses the given switch entity."""
        for outlet in room.get("outlets", []):
            otype = outlet.get("type", "outlet")
            if otype == "outlet":
                if outlet.get("plug1_switch") == switch_entity:
                    return outlet
                if outlet.get("plug2_switch") == switch_entity:
                    return outlet
            elif otype == "light":
                if outlet.get("switch_entity") == switch_entity:
                    return outlet
            elif otype in ("vent", "wall_heater"):
                if outlet.get("switch_entity") == switch_entity:
                    return outlet
            elif otype in ("single_outlet", "minisplit", "stove", "microwave", "fridge"):
                if outlet.get("plug1_switch") == switch_entity:
                    return outlet
        return None

    def _presence_restore_outlet_classification(
        self, room: dict, restored_switch_ids: list[str]
    ) -> tuple[list[str], list[str]]:
        """Split restored switches into (ac_outlet_names, other_outlet_names).

        Used by the smarter presence-restore TTS so the spoken message reflects
        what was actually turned back on: AC only, outlets only, or both.
        """
        ac_names: list[str] = []
        other_names: list[str] = []
        seen: set[str] = set()
        for sw in restored_switch_ids:
            if not sw or sw in seen:
                continue
            seen.add(sw)
            outlet = self._find_outlet_by_switch(room, sw)
            if not outlet:
                other_names.append(sw)
                continue
            name = str(outlet.get("name") or "").strip()
            if outlet.get("type") == "minisplit":
                ac_names.append(name or "Air Conditioner")
            else:
                other_names.append(name or "outlet")
        return ac_names, other_names

    async def _async_speak_presence_restore_tts_for_room(
        self,
        room: dict,
        restored_switch_ids: list[str],
    ) -> None:
        """Speak a context-aware TTS when zone-based presence restores devices.

        - AC only → "Turning on the air conditioning."
        - Outlets only → "Turning on the outlets." (or single outlet name)
        - Both → "Turning on the outlets and air conditioning."
        - Neither → no TTS.

        Only fires for rooms with a configured presence person + zone entities
        (zone-based presence), so it complements the per-outlet binary_sensor
        presence-detected TTS rather than replacing it.
        """
        mp = (room.get("media_player") or "").strip()
        if not mp.startswith("media_player."):
            return
        person_ent = _normalize_presence_person_entity(room.get("presence_person_entity"))
        if not person_ent:
            return
        zones = room.get("presence_zone_entities") or []
        if not zones:
            return
        tts_settings = self.config_manager.energy_config.get("tts_settings") or {}
        if not tts_settings.get("presence_tts_enabled", True):
            return
        if not self._tts_line_enabled(tts_settings, "presence_detected"):
            return

        person_state = self.hass.states.get(person_ent)
        if person_state and person_state.attributes:
            person_name = (
                person_state.attributes.get("friendly_name")
                or str(person_ent).replace("person.", "").replace("_", " ").title()
            )
        else:
            person_name = str(person_ent).replace("person.", "").replace("_", " ").title()

        ac_names, other_names = self._presence_restore_outlet_classification(
            room, restored_switch_ids
        )
        has_ac = bool(ac_names)
        has_outlets = bool(other_names)
        if not has_ac and not has_outlets:
            return
        if has_ac and has_outlets:
            phrase = "the outlets and air conditioning"
        elif has_ac:
            phrase = "the air conditioning"
        else:
            phrase = "the outlets" if len(other_names) > 1 else f"the {other_names[0]}"

        prefix = tts_settings.get("prefix", DEFAULT_TTS_PREFIX)
        room_name = str(room.get("name") or "Room")
        message = f"{prefix} {person_name} is nearby, turning on {phrase} in {room_name}."
        await self._async_speak_appliance_automation_tts(room, message)

    async def _tick_vent_automation(
        self, room: dict, room_id: str, outlet: dict, now: datetime
    ) -> None:
        if outlet.get("type") != "vent":
            return
        key = self._appliance_automation_key(room_id, outlet)
        if not outlet.get("vent_automation_enabled"):
            self._vent_automation_state.pop(key, None)
            return
        if not self._anyone_in_any_zone():
            return
        switch = outlet.get("switch_entity")
        pres_ent = str(outlet.get("vent_presence_entity") or "").strip()
        if not self._is_appliance_control_entity(switch) or not pres_ent:
            return
        on_deb = max(0, int(outlet.get("vent_on_debounce_seconds", 30)))
        off_after = max(1, int(outlet.get("vent_off_after_no_presence_seconds", 300)))
        st = self._vent_automation_state.setdefault(
            key, {"armed": False, "presence_since": None, "no_presence_since": None}
        )
        pres = self._binary_presence_positive(pres_ent)
        sw_on = self._appliance_entity_is_on(switch)

        if not sw_on:
            st["armed"] = False
            st["no_presence_since"] = None

        if pres:
            st["no_presence_since"] = None
            if not sw_on:
                if st["presence_since"] is None:
                    st["presence_since"] = now
                elif (now - st["presence_since"]).total_seconds() >= on_deb:
                    await self._async_appliance_power_set(str(switch), True)
                    st["armed"] = True
                    st["presence_since"] = None
                    tts_settings = (
                        self.config_manager.energy_config.get("tts_settings") or {}
                    )
                    if self._tts_line_enabled(tts_settings, "vent_automation"):
                        prefix = tts_settings.get("prefix", DEFAULT_TTS_PREFIX)
                        tmpl = (
                            tts_settings.get("vent_automation_on_msg") or ""
                        ).strip() or DEFAULT_VENT_AUTOMATION_ON_MSG
                        room_name = str(room.get("name") or room_id)
                        outlet_name = str(outlet.get("name") or "vent")
                        try:
                            msg = tmpl.format(
                                prefix=prefix,
                                room_name=room_name,
                                outlet_name=outlet_name,
                            )
                            await self._async_speak_appliance_automation_tts(room, msg)
                        except (KeyError, ValueError) as e:
                            _LOGGER.warning("Vent automation TTS template failed: %s", e)
                    await self._send_notification_to_room_person(
                        room,
                        "vent_auto_on",
                        {
                            "room_name": room_name,
                            "outlet_name": outlet_name,
                        },
                        "Vent Auto On",
                        f"Motion detected in {room_name}, turning on {outlet_name}.",
                        integration_auto=True,
                    )
        else:
            st["presence_since"] = None
            if sw_on and st.get("armed"):
                if st["no_presence_since"] is None:
                    st["no_presence_since"] = now
                elif (now - st["no_presence_since"]).total_seconds() >= off_after:
                    await self._async_appliance_power_set(str(switch), False)
                    st["armed"] = False
                    st["no_presence_since"] = None
                    room_name = str(room.get("name") or room_id)
                    outlet_name = str(outlet.get("name") or "vent")
                    await self._send_notification_to_room_person(
                        room,
                        "vent_auto_off",
                        {
                            "room_name": room_name,
                            "outlet_name": outlet_name,
                        },
                        "Vent Auto Off",
                        f"No motion in {room_name}, turning off {outlet_name}.",
                        integration_auto=True,
                    )

    async def _tick_wall_heater_automation(
        self, room: dict, room_id: str, outlet: dict, now: datetime
    ) -> None:
        """Smart wall heater automation with state machine, weather awareness, and optimization."""
        if outlet.get("type") != "wall_heater":
            return
        key = self._appliance_automation_key(room_id, outlet)
        switch = outlet.get("switch_entity")
        if not self._is_appliance_control_entity(switch):
            return

        auto_enabled = bool(outlet.get("heater_automation_enabled"))
        if auto_enabled and not self._anyone_in_any_zone():
            return

        switch_ent = str(switch)
        stay_min = max(1, min(240, int(outlet.get("heater_stay_on_minutes", 5))))
        stay_delta = timedelta(minutes=stay_min)

        st = self._heater_automation_state.setdefault(
            key,
            {
                "run_until": None,
                "last_on": None,
                "prev_sw_on": None,
                "prev_presence": False,
                "mode": None,
                "auto_session_announced": False,
            },
        )
        smart_st = self._get_heater_smart_state(key)

        sw_on = self._appliance_entity_is_on(switch)
        internal = switch_ent in self._integration_internal_switch_ids

        temp_ent = str(outlet.get("heater_temperature_entity") or "").strip()
        temp: float | None = None
        if temp_ent.startswith("sensor."):
            temp = self._parse_temperature_sensor(temp_ent)

        optimization_enabled = bool(outlet.get("heater_optimization_enabled", True))
        hysteresis = float(outlet.get("heater_hysteresis_band", 2.0) or 2.0)
        duty_enabled = bool(outlet.get("heater_duty_cycle_enabled"))
        duty_on_mins = max(1, int(outlet.get("heater_duty_on_minutes", 5) or 5))
        duty_off_mins = max(1, int(outlet.get("heater_duty_off_minutes", 2) or 2))
        duty_margin = float(outlet.get("heater_duty_comfort_margin", 1.0) or 1.0)
        power_aware = bool(outlet.get("heater_power_aware_enabled"))
        power_threshold = int(outlet.get("heater_power_threshold_watts", 500) or 500)
        learning_enabled = bool(outlet.get("heater_learning_enabled", True))
        preheat_mins = int(outlet.get("heater_preheat_minutes", 30) or 30)
        weather_ent = str(outlet.get("heater_weather_entity") or "").strip()
        cold_boost_enabled = bool(outlet.get("heater_cold_boost_enabled"))

        need_presence = bool(outlet.get("heater_presence_optional_enabled"))
        pres_turn_on = bool(outlet.get("heater_presence_turn_on_enabled"))
        pres_ent = str(outlet.get("heater_presence_entity") or "").strip()
        pres_ok = self._binary_presence_positive(pres_ent) if pres_ent else False
        prev_pres = bool(st.get("prev_presence"))
        pres_edge = bool(pres_ent and pres_ok and not prev_pres)
        cooldown = max(0, int(outlet.get("heater_presence_cooldown_seconds", 60)))

        if st.get("prev_sw_on") is None:
            st["prev_sw_on"] = sw_on
            st["prev_presence"] = pres_ok if pres_ent else False
            return

        prev_sw = bool(st["prev_sw_on"])
        room_name = str(room.get("name") or room_id)
        outlet_name = str(outlet.get("name") or "heater")

        if temp is not None and learning_enabled:
            self._update_temp_history(key, now, temp, sw_on)
            self._calculate_thermal_rates(key)

        outdoor_temp: float | None = None
        forecast: list[dict] = []
        if weather_ent and (optimization_enabled or cold_boost_enabled):
            outdoor_temp, forecast = await self._get_outdoor_and_forecast(weather_ent)

        threshold, comfort, _boost_active = resolve_wall_heater_effective_temperatures(
            outlet, outdoor_temp
        )

        def _cooldown_blocks() -> bool:
            if not need_presence:
                return False
            last_on = st.get("last_on")
            if last_on and (now - last_on).total_seconds() < cooldown:
                return True
            return False

        def _presence_allows() -> bool:
            if not need_presence:
                return True
            if not pres_ent or not pres_ok:
                return False
            if _cooldown_blocks():
                return False
            return True

        async def _turn_heater_on() -> None:
            await self._async_wall_heater_set_switch(switch_ent, True)
            st["last_on"] = now
            smart_st["heating_since"] = now

        async def _turn_heater_off() -> None:
            await self._async_wall_heater_set_switch(switch_ent, False)
            smart_st["heating_since"] = None

        async def _announce_heater_on() -> None:
            if st.get("auto_session_announced"):
                return
            tts_settings = self.config_manager.energy_config.get("tts_settings") or {}
            if self._tts_line_enabled(tts_settings, "heater_automation"):
                prefix = tts_settings.get("prefix", DEFAULT_TTS_PREFIX)
                tmpl = (
                    tts_settings.get("heater_automation_on_msg") or ""
                ).strip() or DEFAULT_HEATER_AUTOMATION_ON_MSG
                comfort_spoken = spoken_cardinal(int(round(comfort)))
                temp_spoken = spoken_cardinal(int(round(temp))) if temp else "unknown"
                try:
                    msg = tmpl.format(
                        prefix=prefix,
                        room_name=room_name,
                        outlet_name=outlet_name,
                        threshold=comfort_spoken,
                        temperature=temp_spoken,
                    )
                    await self._async_speak_appliance_automation_tts(room, msg)
                except (KeyError, ValueError) as e:
                    _LOGGER.warning("Heater automation TTS template failed: %s", e)
            await self._send_notification_to_room_person(
                room,
                "heater_auto_on",
                {
                    "room_name": room_name,
                    "outlet_name": outlet_name,
                    "temperature": str(int(round(temp))) if temp else "?",
                    "threshold": str(int(round(comfort))),
                },
                "Heater Auto On",
                f"{room_name} is {int(round(temp)) if temp else '?'}°, turning on {outlet_name}.",
                integration_auto=True,
            )
            st["auto_session_announced"] = True

        async def _announce_heater_off() -> None:
            if temp is not None:
                await self._send_notification_to_room_person(
                    room,
                    "heater_auto_off",
                    {
                        "room_name": room_name,
                        "outlet_name": outlet_name,
                        "temperature": str(int(round(temp))),
                        "comfort": str(int(round(comfort))),
                    },
                    "Heater Auto Off",
                    f"{room_name} reached {int(round(temp))}°, turning off {outlet_name}.",
                    integration_auto=True,
                )

        if sw_on and not prev_sw and not internal:
            st["mode"] = "manual"
            st["run_until"] = now + stay_delta
            smart_st["smart_mode"] = "manual"

        if not sw_on and st.get("mode") == "manual":
            st["run_until"] = None
            st["mode"] = None
            st["auto_session_announced"] = False
            smart_st["smart_mode"] = "idle"

        mode = st.get("mode")

        if mode == "manual":
            if temp is not None and temp >= comfort:
                await _turn_heater_off()
                st["run_until"] = None
                st["mode"] = None
                smart_st["smart_mode"] = "idle"
            elif st.get("run_until") and now >= st["run_until"]:
                await _turn_heater_off()
                st["run_until"] = None
                st["mode"] = None
                smart_st["smart_mode"] = "idle"
            st["prev_sw_on"] = self._appliance_entity_is_on(switch)
            st["prev_presence"] = pres_ok if pres_ent else False
            return

        sw_on = self._appliance_entity_is_on(switch)
        smart_mode = smart_st.get("smart_mode", "idle")

        if not auto_enabled:
            if sw_on and st.get("mode") == "auto":
                await _turn_heater_off()
                st["mode"] = None
                st["auto_session_announced"] = False
                smart_st["smart_mode"] = "idle"
            st["prev_sw_on"] = sw_on
            st["prev_presence"] = pres_ok if pres_ent else False
            return

        if temp is None:
            if sw_on and st.get("mode") == "auto":
                await _turn_heater_off()
                st["mode"] = None
                st["auto_session_announced"] = False
                smart_st["smart_mode"] = "idle"
            st["prev_sw_on"] = self._appliance_entity_is_on(switch)
            st["prev_presence"] = pres_ok if pres_ent else False
            return

        turn_on_temp = comfort - hysteresis if optimization_enabled else comfort - 1.0
        turn_off_temp = comfort

        if smart_mode == "idle":
            should_heat = False
            if int(temp) < int(turn_on_temp):
                if _presence_allows() or not need_presence:
                    should_heat = True
            elif pres_turn_on and pres_edge and int(temp) < int(turn_off_temp):
                if _presence_allows():
                    should_heat = True
            elif optimization_enabled and preheat_mins > 0:
                if self._forecast_needs_preheat(forecast, outdoor_temp, temp, comfort, preheat_mins):
                    if _presence_allows() or not need_presence:
                        should_heat = True
                        smart_st["smart_mode"] = "pre_heating"

            if should_heat:
                blocker = self._heater_door_window_blocks(outlet)
                if blocker:
                    room_name = str(room.get("name") or room_id)
                    await self._announce_heater_blocked(room, room_name, blocker)
                    return
                await _turn_heater_on()
                st["mode"] = "auto"
                if smart_st.get("smart_mode") != "pre_heating":
                    smart_st["smart_mode"] = "heating"
                await _announce_heater_on()

        elif smart_mode in ("heating", "pre_heating"):
            if temp >= turn_off_temp:
                await _turn_heater_off()
                st["mode"] = None
                st["auto_session_announced"] = False
                smart_st["smart_mode"] = "idle"
                await _announce_heater_off()
            elif optimization_enabled and duty_enabled:
                close_to_comfort = temp >= (comfort - duty_margin)
                heating_since = smart_st.get("heating_since")
                if close_to_comfort and heating_since and (now - heating_since).total_seconds() >= duty_on_mins * 60:
                    await _turn_heater_off()
                    smart_st["smart_mode"] = "duty_pause"
                    smart_st["duty_pause_until"] = now + timedelta(minutes=duty_off_mins)
            elif optimization_enabled and power_aware:
                home_power = self._sum_all_rooms_watts_only()
                heater_power = 0.0
                if outlet.get("power_source") == "sensor":
                    pe = outlet.get("power_sensor_entity")
                    if pe and sw_on:
                        heater_power = self._get_power_value(pe)
                elif sw_on:
                    heater_power = float(outlet.get("watts_when_on", 0) or 0)
                other_power = home_power - heater_power
                if other_power > power_threshold:
                    await _turn_heater_off()
                    smart_st["smart_mode"] = "power_pause"
                    smart_st["power_pause_since"] = now

        elif smart_mode == "duty_pause":
            duty_until = smart_st.get("duty_pause_until")
            if duty_until and now >= duty_until:
                if temp < turn_off_temp:
                    await _turn_heater_on()
                    smart_st["smart_mode"] = "heating"
                else:
                    smart_st["smart_mode"] = "idle"
                    st["mode"] = None
                    st["auto_session_announced"] = False

        elif smart_mode == "power_pause":
            home_power = self._sum_all_rooms_watts_only()
            if home_power <= power_threshold * 0.8:
                if temp < turn_off_temp:
                    await _turn_heater_on()
                    smart_st["smart_mode"] = "heating"
                else:
                    smart_st["smart_mode"] = "idle"
                    st["mode"] = None
                    st["auto_session_announced"] = False

        st["prev_sw_on"] = self._appliance_entity_is_on(switch)
        st["prev_presence"] = pres_ok if pres_ent else False

    @staticmethod
    def _light_automation_segment_identity(segment: dict) -> str:
        """Stable id for the active schedule row (first match wins ordering in UI)."""
        return "|".join(
            str(segment.get(k, ""))
            for k in ("start", "end", "action", "light_mode", "enforcement_interval")
        )

    def _light_automation_tick_state(self, state_key: str) -> dict:
        st = self._light_auto_apply_state.get(state_key)
        if st is None:
            st = {"seg_id": None, "t0": None, "last_apply_mono": None}
            self._light_auto_apply_state[state_key] = st
        return st

    async def _tick_light_automation(self, now: datetime) -> None:
        """Run light schedules on segment transitions + short post-transition reconcile only.

        The energy monitor ticks every second; re-applying while still inside the same
        schedule window caused lights/switches to thrash all day. We only run a full
        apply when the active segment *changes* (or on first observation), then at
        most every ``enforcement_interval`` seconds for `_LIGHT_AUTO_BURST_ENFORCE_SEC`
        seconds, then stay idle until the next transition.
        """
        import time as time_mod

        try:
            if not self.config_manager.light_automations_cache_loaded():
                automations = await self.hass.async_add_executor_job(
                    self.config_manager.get_all_light_automations
                )
            else:
                automations = self.config_manager.get_all_light_automations()
        except Exception as e:
            _LOGGER.debug("Failed to load light automations: %s", e)
            return

        if not automations:
            return

        current_mins = now.hour * 60 + now.minute
        now_mono = time_mod.monotonic()
        burst = float(self._LIGHT_AUTO_BURST_ENFORCE_SEC)

        for room_id, room_auto in automations.items():
            room = self._find_room_by_id(room_id)
            if not room:
                continue

            group_auto = room_auto.get("group_automation", {}) or {}

            gkey = f"group:{room_id}"
            if not group_auto.get("enabled"):
                self._light_auto_apply_state.pop(gkey, None)
            else:
                matched: dict | None = None
                for segment in group_auto.get("segments", []):
                    if self._time_in_segment(current_mins, segment):
                        matched = segment
                        break
                gst = self._light_automation_tick_state(gkey)
                if matched is None:
                    if gst.get("seg_id") is not None:
                        gst["seg_id"] = None
                        gst["t0"] = None
                        gst["last_apply_mono"] = None
                else:
                    seg_id = self._light_automation_segment_identity(matched)
                    if gst.get("seg_id") != seg_id:
                        gst["seg_id"] = seg_id
                        gst["t0"] = now_mono
                        gst["last_apply_mono"] = None
                        # On apply failure, set last_apply_mono to now so the next
                        # tick waits the full interval instead of re-applying every
                        # second for 60s (audit BUG 2).
                        try:
                            await self._apply_light_group_segment(
                                room, matched, full_mode_converge=True
                            )
                        except Exception as e:
                            _LOGGER.warning(
                                "Light automation group apply failed for room %s: %s",
                                room_id, e,
                            )
                        gst["last_apply_mono"] = now_mono
                    else:
                        t0 = gst.get("t0")
                        if t0 is None:
                            gst["t0"] = now_mono
                            t0 = now_mono
                        elapsed = now_mono - float(t0)
                        if elapsed >= burst:
                            continue
                        interval = max(
                            10,
                            min(3600, int(matched.get("enforcement_interval", 60))),
                        )
                        last = gst.get("last_apply_mono")
                        if last is None or (now_mono - float(last)) >= float(interval):
                            try:
                                await self._apply_light_group_segment(
                                    room, matched, full_mode_converge=False
                                )
                            except Exception as e:
                                _LOGGER.warning(
                                    "Light automation group reconcile failed for room %s: %s",
                                    room_id, e,
                                )
                            gst["last_apply_mono"] = now_mono

            for entity_id, light_auto in room_auto.get("individual_automations", {}).items():
                ikey = f"ind:{room_id}:{entity_id}"
                if not light_auto.get("enabled"):
                    self._light_auto_apply_state.pop(ikey, None)
                    continue
                matched_i: dict | None = None
                for segment in light_auto.get("segments", []):
                    if self._time_in_segment(current_mins, segment):
                        matched_i = segment
                        break
                ist = self._light_automation_tick_state(ikey)
                if matched_i is None:
                    if ist.get("seg_id") is not None:
                        ist["seg_id"] = None
                        ist["t0"] = None
                        ist["last_apply_mono"] = None
                    continue
                seg_id_i = self._light_automation_segment_identity(matched_i)
                if ist.get("seg_id") != seg_id_i:
                    ist["seg_id"] = seg_id_i
                    ist["t0"] = now_mono
                    ist["last_apply_mono"] = None
                    try:
                        await self._apply_light_single_segment(
                            entity_id, matched_i, full_mode_converge=True
                        )
                    except Exception as e:
                        _LOGGER.warning(
                            "Light automation individual apply failed for %s: %s",
                            entity_id, e,
                        )
                    ist["last_apply_mono"] = now_mono
                else:
                    t0i = ist.get("t0")
                    if t0i is None:
                        ist["t0"] = now_mono
                        t0i = now_mono
                    elapsed_i = now_mono - float(t0i)
                    if elapsed_i >= burst:
                        continue
                    interval_i = max(
                        10,
                        min(3600, int(matched_i.get("enforcement_interval", 60))),
                    )
                    last_i = ist.get("last_apply_mono")
                    if last_i is None or (now_mono - float(last_i)) >= float(interval_i):
                        try:
                            await self._apply_light_single_segment(
                                entity_id, matched_i, full_mode_converge=False
                            )
                        except Exception as e:
                            _LOGGER.warning(
                                "Light automation individual reconcile failed for %s: %s",
                                entity_id, e,
                            )
                        ist["last_apply_mono"] = now_mono

    def _time_in_segment(self, current_mins: int, segment: dict) -> bool:
        """Check if current time (in minutes) is within segment range."""
        start_str = segment.get("start", "00:00")
        end_str = segment.get("end", "00:00")

        try:
            sh, sm = map(int, start_str.split(":"))
            eh, em = map(int, end_str.split(":"))
        except (ValueError, AttributeError):
            return False

        start_mins = sh * 60 + sm
        end_mins = eh * 60 + em

        if start_mins <= end_mins:
            return start_mins <= current_mins < end_mins
        else:
            return current_mins >= start_mins or current_mins < end_mins

    def _find_room_by_id(self, room_id: str) -> dict | None:
        """Find a room by its ID."""
        rooms = self.config_manager.energy_config.get("rooms", [])
        for room in rooms:
            rid = room.get("id", room["name"].lower().replace(" ", "_"))
            if rid == room_id:
                return room
        return None

    def _entity_usable(self, entity_id: str) -> bool:
        """True when HA reports a state other than unavailable/unknown."""
        if not entity_id:
            return False
        st = self.hass.states.get(entity_id)
        if st is None:
            return False
        raw = (st.state or "").lower()
        return raw not in ("unavailable", "unknown")

    def _skip_light_auto_if_unusable(self, entity_id: str) -> bool:
        """Return True when automation should wait for entity to become ready."""
        if self._entity_usable(entity_id):
            self._light_auto_unavail_logged.discard(entity_id)
            return False
        if entity_id not in self._light_auto_unavail_logged:
            _LOGGER.debug(
                "Light automation: skipping %s until entity is available",
                entity_id,
            )
            self._light_auto_unavail_logged.add(entity_id)
        return True

    async def _apply_light_group_segment(
        self, room: dict, segment: dict, *, full_mode_converge: bool = True
    ) -> None:
        """Apply a light automation segment to all mapped lights on every light appliance in the room."""
        by_entity: dict[str, tuple[bool, bool]] = {}
        for outlet in room.get("outlets", []):
            if outlet.get("type") != "light":
                continue
            for light in outlet.get("light_entities") or []:
                entity_id, is_wrgb, is_tuya = _normalize_light_entity_row(light)
                if not entity_id:
                    continue
                if entity_id in by_entity:
                    ow, ot = by_entity[entity_id]
                    by_entity[entity_id] = (ow or is_wrgb, ot or is_tuya)
                else:
                    by_entity[entity_id] = (is_wrgb, is_tuya)
        targets = [
            (eid, w, t)
            for eid, (w, t) in by_entity.items()
            if not self._skip_light_auto_if_unusable(eid)
        ]
        if not targets:
            return
        import time

        # Never pre-energize appliance switches for "off" segments — that powers loads
        # unrelated to the intended automation and feels like random switch-ons.
        seg_action = segment.get("action", "on")
        switch_meta: dict[str, dict] = {}
        if seg_action in ("on", "mode"):
            for eid, _, _ in targets:
                outlet = self._find_light_outlet_for_entity(eid)
                sw = outlet.get("switch_entity") if outlet else None
                if not self._is_switch_entity_id(sw):
                    continue
                if self._skip_light_auto_if_unusable(sw):
                    continue
                if sw in switch_meta:
                    continue
                was_off = not self._switch_entity_is_on(sw)
                if was_off:
                    await self._async_switch_set(sw, True)
                switch_meta[sw] = {
                    "was_off": was_off,
                    "t0": time.monotonic() if was_off else None,
                }

        results: list = []
        try:
            results = await asyncio.gather(
                *[
                    self._apply_light_action(
                        eid,
                        segment,
                        is_wrgb=w,
                        is_tuya=t,
                        defer_appliance_switch=True,
                        full_mode_converge=full_mode_converge,
                    )
                    for eid, w, t in targets
                ],
                return_exceptions=True,
            )
        finally:
            if segment.get("action", "on") == "mode":
                for sw, meta in switch_meta.items():
                    if not meta.get("was_off"):
                        continue
                    t0 = meta.get("t0")
                    if t0 is not None:
                        rem = 60.0 - (time.monotonic() - t0)
                        if rem > 0:
                            await asyncio.sleep(rem)
                    await self._async_switch_set(sw, False)

        for (eid, _, _), res in zip(targets, results):
            if isinstance(res, Exception):
                _LOGGER.warning(
                    "Light automation group: failed for %s: %s",
                    eid,
                    res,
                )

    async def _apply_light_single_segment(
        self, entity_id: str, segment: dict, *, full_mode_converge: bool = True
    ) -> None:
        """Apply a light automation segment to a single light."""
        if self._skip_light_auto_if_unusable(entity_id):
            return
        room_config = self._find_light_config(entity_id)
        is_wrgb = room_config.get("wrgb", False) if room_config else False
        is_tuya = room_config.get("tuya", False) if room_config else False

        await self._apply_light_action(
            entity_id,
            segment,
            is_wrgb=is_wrgb,
            is_tuya=is_tuya,
            full_mode_converge=full_mode_converge,
        )

    def _find_light_config(self, entity_id: str) -> dict | None:
        """Find light entity configuration."""
        rooms = self.config_manager.energy_config.get("rooms", [])
        for room in rooms:
            for outlet in room.get("outlets", []):
                if outlet.get("type") != "light":
                    continue
                for light in outlet.get("light_entities", []):
                    eid, _, _ = _normalize_light_entity_row(light)
                    if eid == entity_id:
                        if isinstance(light, dict):
                            return light
                        return {
                            "entity_id": eid,
                            "watts": 0,
                            "wrgb": False,
                            "tuya": False,
                        }
        return None

    def _find_light_outlet_for_entity(self, entity_id: str) -> dict | None:
        """Return the light-type outlet dict that owns this light.* entity (for switch_entity)."""
        rooms = self.config_manager.energy_config.get("rooms", [])
        for room in rooms:
            for outlet in room.get("outlets", []):
                if outlet.get("type") != "light":
                    continue
                for light in outlet.get("light_entities", []):
                    eid, _, _ = _normalize_light_entity_row(light)
                    if eid == entity_id:
                        return outlet
        return None

    @staticmethod
    def _to_kelvin(value: float | int | None, attr_name: str) -> float | None:
        """Normalize a color-temperature attribute/target to kelvin.

        HA lights expose ``color_temp_kelvin`` (kelvin) OR ``color_temp`` (mireds).
        Comparing them directly caused infinite re-apply on mireds-only lights
        (audit BUG 6). This helper converts mireds to kelvin via 1e6/mireds so the
        two are always compared in the same unit.
        """
        if value is None:
            return None
        try:
            v = float(value)
        except (TypeError, ValueError):
            return None
        if attr_name == "color_temp_kelvin":
            return v
        # mireds: lower is cooler/blue, higher is warmer/red — invert to kelvin.
        if v <= 0:
            return None
        return 1_000_000.0 / v

    def _light_state_matches_segment(
        self,
        entity_id: str,
        segment: dict,
        attrs: dict,
        is_wrgb: bool,
        is_tuya: bool,
        state_key: str,
    ) -> bool:
        """True if light state already satisfies the segment (same thresholds as apply logic)."""
        light_mode = segment.get("light_mode", "white")
        brightness_pct = segment.get("brightness")
        color_temp = segment.get("color_temp")
        hs_color = segment.get("hs_color")
        tuya_scene = segment.get("tuya_scene")

        if is_tuya and tuya_scene and light_mode == "scene":
            # Previously this compared an in-memory hash() of the encoded scene hex,
            # which can never detect external/manual scene changes and caused the
            # full_mode_converge loop to re-send the scene for up to 45s. Instead,
            # read the actual text.{light}_scene entity state and compare the
            # freshly-encoded hex against it (audit BUG 4).
            scene_hex = self._encode_tuya_scene_hex(tuya_scene)
            if not scene_hex:
                return True
            light_name = entity_id.replace("light.", "", 1)
            scene_text_entity = f"text.{light_name}_scene"
            st = self.hass.states.get(scene_text_entity)
            if st is None or st.state in (None, "", "unknown", "unavailable"):
                return False
            return str(st.state).strip().lower() == scene_hex.strip().lower()

        if brightness_pct is not None:
            cur = attrs.get("brightness")
            target = int(brightness_pct * 255 / 100)
            # Compare as floats so the match check and the apply check agree at
            # the tolerance boundary (audit BUG 7).
            if cur is None or abs(float(cur) - float(target)) > 5:
                return False

        if is_wrgb and light_mode == "color" and hs_color is not None:
            cur_hs = attrs.get("hs_color")
            if cur_hs is None or (
                abs(cur_hs[0] - hs_color[0]) > 5 or abs(cur_hs[1] - hs_color[1]) > 5
            ):
                return False
        elif is_wrgb and light_mode == "white" and color_temp is not None:
            # Compare in kelvin on both sides; mireds-only lights previously
            # caused infinite re-apply (audit BUG 6).
            cur_k = self._to_kelvin(attrs.get("color_temp_kelvin"), "color_temp_kelvin") \
                or self._to_kelvin(attrs.get("color_temp"), "color_temp")
            tgt_k = float(color_temp)
            if cur_k is None or abs(cur_k - tgt_k) > 100:
                return False

        return True

    def pause_light_enforcement(self, seconds: int = 30) -> None:
        """Pause light automation enforcement for a given number of seconds."""
        import time
        self._light_enforcement_paused_until = time.monotonic() + seconds
        _LOGGER.info("Light automation enforcement paused for %d seconds", seconds)

    def _should_skip_light_enforcement(self, entity_id: str, enforcement_interval: int) -> bool:
        """Check if light enforcement should be skipped due to pause or interval.

        Uses ``time.monotonic`` (the same clock as the tick loop's
        ``_light_auto_apply_state``) so the two throttle paths can't disagree
        (audit BUG 3).
        """
        import time
        now_mono = time.monotonic()
        if now_mono < self._light_enforcement_paused_until:
            return True
        last_run = self._light_enforcement_last_run.get(entity_id, 0.0)
        if now_mono - last_run < enforcement_interval:
            return True
        return False

    def _mark_light_enforcement_run(self, entity_id: str) -> None:
        """Mark that enforcement ran for this light."""
        import time
        self._light_enforcement_last_run[entity_id] = time.monotonic()

    def _encode_tuya_scene_hex(self, scene: dict) -> str:
        """Encode Tuya scene data into hex string for scene_data_v2 format.

        Delegates to the canonical implementation in :mod:`light_automation`
        (audit BUG 22: previously a drifted JS copy lived in the frontend too).
        """
        from .light_automation import encode_tuya_scene_hex
        return encode_tuya_scene_hex(scene)

    async def _async_tuya_clear_scene_effect_if_active(
        self, entity_id: str, attrs: dict
    ) -> dict:
        """If the light reports Scene effect, switch to the integration's off effect (exit scene mode)."""
        effect_list = attrs.get("effect_list") or []
        if not effect_list:
            return attrs
        current = attrs.get("effect")
        scene_entry = next((e for e in effect_list if str(e).lower() == "scene"), None)
        off_entry = next((e for e in effect_list if str(e).lower() == "off"), None)
        if not off_entry:
            return attrs
        in_scene = False
        if current is not None:
            cur_l = str(current).strip().lower()
            if cur_l == "scene":
                in_scene = True
            elif scene_entry is not None and str(current) == str(scene_entry):
                in_scene = True
        if not in_scene:
            return attrs
        try:
            await self.hass.services.async_call(
                "light",
                "turn_on",
                {"entity_id": entity_id, "effect": off_entry},
                blocking=True,
            )
        except Exception as e:
            _LOGGER.warning(
                "Light automation: could not exit scene effect on %s: %s",
                entity_id,
                e,
            )
            return attrs
        st = self.hass.states.get(entity_id)
        if st and st.attributes:
            return dict(st.attributes)
        return attrs

    async def _async_run_light_automation_effects(
        self,
        entity_id: str,
        segment: dict,
        is_wrgb: bool,
        is_tuya: bool,
        action: str,
        state_key: str,
        enforcement_interval: int,
        *,
        skip_enforcement: bool = False,
    ) -> None:
        """Apply scene/color/white/brightness from segment (shared core for retries and normal path)."""
        current_state = self.hass.states.get(entity_id)
        current_on = current_state and current_state.state == "on"
        attrs = current_state.attributes if current_state else {}

        light_mode = segment.get("light_mode", "white")
        tuya_scene = segment.get("tuya_scene")

        if is_tuya and current_on and light_mode != "scene":
            attrs = await self._async_tuya_clear_scene_effect_if_active(entity_id, attrs)

        if (
            not skip_enforcement
            and current_on
            and self._should_skip_light_enforcement(entity_id, enforcement_interval)
        ):
            return

        brightness_pct = segment.get("brightness")
        color_temp = segment.get("color_temp")
        hs_color = segment.get("hs_color")

        if is_tuya and tuya_scene and light_mode == "scene":
            if not current_on and action == "on":
                try:
                    await self.hass.services.async_call(
                        "light",
                        "turn_on",
                        {"entity_id": entity_id},
                        blocking=True,
                    )
                    current_state = self.hass.states.get(entity_id)
                    current_on = current_state is not None and current_state.state == "on"
                    attrs = current_state.attributes if current_state else {}
                except Exception as e:
                    _LOGGER.warning(
                        "Light automation: cannot turn on %s before scene: %s",
                        entity_id,
                        e,
                    )
                    self._mark_light_enforcement_run(entity_id)
                    return
            if not current_on:
                self._mark_light_enforcement_run(entity_id)
                return

            effect_list = attrs.get("effect_list") or []
            scene_effect = next(
                (e for e in effect_list if str(e).lower() == "scene"), None
            )
            if scene_effect:
                try:
                    await self.hass.services.async_call(
                        "light",
                        "turn_on",
                        {"entity_id": entity_id, "effect": scene_effect},
                        blocking=True,
                    )
                except Exception as e:
                    _LOGGER.warning(
                        "Light automation: failed to set effect=%s on %s: %s",
                        scene_effect,
                        entity_id,
                        e,
                    )

            light_name = entity_id.replace("light.", "", 1)
            scene_text_entity = f"text.{light_name}_scene"
            from homeassistant.helpers import entity_registry as er

            ent_reg = er.async_get(self.hass)
            entry = ent_reg.async_get(scene_text_entity)
            if entry and entry.disabled_by is not None:
                ent_reg.async_update_entity(scene_text_entity, disabled_by=None)
                _LOGGER.info(
                    "Light automation: enabled disabled entity %s for %s",
                    scene_text_entity,
                    entity_id,
                )
                await asyncio.sleep(0.5)

            scene_hex = self._encode_tuya_scene_hex(tuya_scene)
            if not scene_hex:
                _LOGGER.warning("Light automation: empty scene hex for %s", entity_id)
                self._mark_light_enforcement_run(entity_id)
                return
            scene_state = self.hass.states.get(scene_text_entity)
            if scene_state is None:
                _LOGGER.warning(
                    "Scene text entity %s does not exist for light %s.",
                    scene_text_entity,
                    entity_id,
                )
                self._mark_light_enforcement_run(entity_id)
                return
            try:
                await self.hass.services.async_call(
                    "text",
                    "set_value",
                    {"entity_id": scene_text_entity, "value": scene_hex},
                )
                self._light_automation_state[state_key] = "tuya_scene_applied"
                self._mark_light_enforcement_run(entity_id)
                _LOGGER.debug(
                    "Light automation: scene for %s via %s",
                    entity_id,
                    scene_text_entity,
                )
            except Exception as e:
                _LOGGER.warning(
                    "Light automation: scene set failed for %s (%s): %s",
                    entity_id,
                    scene_text_entity,
                    e,
                )
            return

        needs_update = False
        service_data: dict = {"entity_id": entity_id}

        if is_wrgb and current_on:
            if brightness_pct is not None:
                current_brightness = attrs.get("brightness")
                target_brightness = int(brightness_pct * 255 / 100)
                if current_brightness is None or abs(current_brightness - target_brightness) > 5:
                    service_data["brightness_pct"] = brightness_pct
                    needs_update = True
            if light_mode == "color" and hs_color is not None:
                current_hs = attrs.get("hs_color")
                if current_hs is None or (
                    abs(current_hs[0] - hs_color[0]) > 5 or abs(current_hs[1] - hs_color[1]) > 5
                ):
                    service_data["hs_color"] = hs_color
                    needs_update = True
            elif light_mode == "white" and color_temp is not None:
                # Compare in kelvin on both sides (audit BUG 6).
                cur_k = self._to_kelvin(attrs.get("color_temp_kelvin"), "color_temp_kelvin") \
                    or self._to_kelvin(attrs.get("color_temp"), "color_temp")
                if cur_k is None or abs(cur_k - float(color_temp)) > 100:
                    service_data["color_temp_kelvin"] = color_temp
                    needs_update = True
        elif not is_wrgb and current_on and brightness_pct is not None:
            current_brightness = attrs.get("brightness")
            target_brightness = int(brightness_pct * 255 / 100)
            if current_brightness is None or abs(current_brightness - target_brightness) > 5:
                service_data["brightness_pct"] = brightness_pct
                needs_update = True

        if action == "on" and not current_on:
            needs_update = True
            if is_wrgb:
                if brightness_pct is not None:
                    service_data["brightness_pct"] = brightness_pct
                if light_mode == "color" and hs_color is not None:
                    service_data["hs_color"] = hs_color
                elif light_mode == "white" and color_temp is not None:
                    service_data["color_temp_kelvin"] = color_temp
            elif brightness_pct is not None:
                service_data["brightness_pct"] = brightness_pct
        elif action == "mode" and not current_on:
            # A "mode" segment on an off light must still apply the configured
            # color/temp/brightness so the user sees the intended state when the
            # light is later switched on. Previously this branch was missing,
            # causing the light to energize at default brightness for 60s then
            # turn off (see audit BUG 1).
            needs_update = True
            if is_wrgb:
                if brightness_pct is not None:
                    service_data["brightness_pct"] = brightness_pct
                if light_mode == "color" and hs_color is not None:
                    service_data["hs_color"] = hs_color
                elif light_mode == "white" and color_temp is not None:
                    service_data["color_temp_kelvin"] = color_temp
            elif brightness_pct is not None:
                service_data["brightness_pct"] = brightness_pct

        if not needs_update:
            self._mark_light_enforcement_run(entity_id)
            return

        action_hash = f"{action}_{brightness_pct}_{color_temp}_{hs_color}_{light_mode}"

        if is_tuya and light_mode in ("color", "white"):
            effect_list = attrs.get("effect_list") or []
            off_effect = next(
                (e for e in effect_list if str(e).lower() == "off"), None
            )
            if off_effect:
                service_data["effect"] = off_effect

        try:
            await self.hass.services.async_call(
                "light",
                "turn_on",
                service_data,
            )
            self._light_automation_state[state_key] = action_hash
            self._mark_light_enforcement_run(entity_id)
            _LOGGER.debug("Light automation: applied to %s with %s", entity_id, service_data)
        except Exception as e:
            _LOGGER.warning("Light automation failed to apply to %s: %s", entity_id, e)

    async def _apply_light_action(
        self,
        entity_id: str,
        segment: dict,
        is_wrgb: bool = False,
        is_tuya: bool = False,
        *,
        defer_appliance_switch: bool = False,
        full_mode_converge: bool = True,
    ) -> None:
        """Apply light action from automation segment with continuous enforcement."""
        import time

        if self._skip_light_auto_if_unusable(entity_id):
            return

        action = segment.get("action", "on")
        enforcement_interval = segment.get("enforcement_interval", 60)
        state_key = f"light_auto_{entity_id}"

        current_state = self.hass.states.get(entity_id)
        current_on = current_state and current_state.state == "on"
        attrs = current_state.attributes if current_state else {}

        if action == "off":
            if current_on:
                if self._should_skip_light_enforcement(entity_id, enforcement_interval):
                    return
                try:
                    await self.hass.services.async_call(
                        "light",
                        "turn_off",
                        {"entity_id": entity_id},
                    )
                    self._light_automation_state[state_key] = "off"
                    self._mark_light_enforcement_run(entity_id)
                    _LOGGER.debug("Light automation: turned off %s", entity_id)
                except Exception as e:
                    _LOGGER.warning("Light automation failed to turn off %s: %s", entity_id, e)
            return

        switch_entity: str | None = None
        switch_was_off = False
        switch_energized_at: float | None = None
        if not defer_appliance_switch:
            outlet = self._find_light_outlet_for_entity(entity_id)
            se = outlet.get("switch_entity") if outlet else None
            if self._is_switch_entity_id(se):
                if self._skip_light_auto_if_unusable(se):
                    return
                switch_entity = se
                if not self._switch_entity_is_on(se):
                    await self._async_switch_set(se, True)
                    switch_was_off = True
                    switch_energized_at = time.monotonic()

        apply_exc: Exception | None = None
        try:
            if action == "mode" and full_mode_converge:
                # Previously 45 iterations / 45s; that re-sent the scene command
                # continuously when the hash-based check could never converge
                # (audit BUG 4). Now that the match check reads the real text
                # entity state, 3 attempts with 1s spacing is enough.
                max_iters = 3
                n = 0
                while n < max_iters:
                    n += 1
                    cs = self.hass.states.get(entity_id)
                    raw = (cs.state or "").lower() if cs else ""
                    if cs and raw not in ("unknown", "unavailable", ""):
                        attrs = dict(cs.attributes or {})
                        current_on = raw == "on"
                        if current_on and self._light_state_matches_segment(
                            entity_id, segment, attrs, is_wrgb, is_tuya, state_key
                        ):
                            break
                    if cs and raw == "off":
                        try:
                            await self.hass.services.async_call(
                                "light",
                                "turn_on",
                                {"entity_id": entity_id},
                                blocking=False,
                            )
                        except Exception:
                            pass
                    await self._async_run_light_automation_effects(
                        entity_id,
                        segment,
                        is_wrgb,
                        is_tuya,
                        action,
                        state_key,
                        enforcement_interval,
                        skip_enforcement=True,
                    )
                    await asyncio.sleep(1.0)

                cs = self.hass.states.get(entity_id)
                raw = (cs.state or "").lower() if cs else ""
                if cs and raw not in ("unknown", "unavailable", ""):
                    attrs = dict(cs.attributes or {})
                    current_on = raw == "on"
                else:
                    current_on = False
                    attrs = {}
                if action == "mode" and not current_on:
                    return
            elif action == "mode" and not full_mode_converge:
                await self._async_run_light_automation_effects(
                    entity_id,
                    segment,
                    is_wrgb,
                    is_tuya,
                    action,
                    state_key,
                    enforcement_interval,
                    skip_enforcement=False,
                )
                return

            await self._async_run_light_automation_effects(
                entity_id,
                segment,
                is_wrgb,
                is_tuya,
                action,
                state_key,
                enforcement_interval,
                skip_enforcement=False,
            )
        except Exception as exc:
            apply_exc = exc
            _LOGGER.warning(
                "Light automation apply failed for %s: %s", entity_id, exc
            )
        finally:
            # Only de-energize a switch we energized for a "mode" segment when the
            # apply succeeded. On failure, leave the switch state alone so the
            # user can see the light is on rather than having it killed after 60s
            # (audit BUG 8).
            if (
                apply_exc is None
                and not defer_appliance_switch
                and action == "mode"
                and switch_was_off
                and switch_entity
            ):
                if switch_energized_at is not None:
                    rem = 60.0 - (time.monotonic() - switch_energized_at)
                    if rem > 0:
                        await asyncio.sleep(rem)
                await self._async_switch_set(switch_entity, False)

    def _presence_auto_off_configured_switch_ids(self, room: dict) -> list[str]:
        """switch.* IDs marked for presence auto-off (on or off), for restore eligibility."""
        ids: list[str] = []
        for outlet in room.get("outlets", []):
            otype = outlet.get("type", "outlet")
            if otype == "outlet":
                if outlet.get("presence_auto_off_plug1"):
                    sw = outlet.get("plug1_switch")
                    if self._is_switch_entity_id(sw):
                        ids.append(str(sw))
                if outlet.get("presence_auto_off_plug2"):
                    sw = outlet.get("plug2_switch")
                    if self._is_switch_entity_id(sw):
                        ids.append(str(sw))
            elif otype == "light" and outlet.get("presence_auto_off"):
                sw = outlet.get("switch_entity")
                if self._is_switch_entity_id(sw):
                    ids.append(str(sw))
            elif otype in ("vent", "wall_heater") and outlet.get("presence_auto_off"):
                sw = outlet.get("switch_entity")
                if self._is_switch_entity_id(sw):
                    ids.append(str(sw))
            elif otype in ("single_outlet", "minisplit", "stove") and outlet.get(
                "presence_auto_off"
            ):
                sw = outlet.get("plug1_switch")
                if self._is_switch_entity_id(sw):
                    ids.append(str(sw))
            elif otype in ("microwave", "fridge") and outlet.get("presence_auto_off"):
                sw = outlet.get("plug1_switch")
                if self._is_switch_entity_id(sw):
                    ids.append(str(sw))
        return list(dict.fromkeys(ids))

    def _presence_auto_off_switch_targets(self, room: dict) -> list[str]:
        """switch.* entity IDs that are on and marked for auto-off when leaving zones."""
        targets: list[str] = []
        for outlet in room.get("outlets", []):
            otype = outlet.get("type", "outlet")
            if otype == "outlet":
                if outlet.get("presence_auto_off_plug1"):
                    sw = outlet.get("plug1_switch")
                    if self._switch_entity_is_on(sw):
                        targets.append(str(sw))
                if outlet.get("presence_auto_off_plug2"):
                    sw = outlet.get("plug2_switch")
                    if self._switch_entity_is_on(sw):
                        targets.append(str(sw))
            elif otype == "light" and outlet.get("presence_auto_off"):
                sw = outlet.get("switch_entity")
                if self._switch_entity_is_on(sw):
                    targets.append(str(sw))
            elif otype in ("vent", "wall_heater") and outlet.get("presence_auto_off"):
                sw = outlet.get("switch_entity")
                if self._switch_entity_is_on(sw):
                    targets.append(str(sw))
            elif otype in ("single_outlet", "minisplit", "stove") and outlet.get(
                "presence_auto_off"
            ):
                sw = outlet.get("plug1_switch")
                if self._switch_entity_is_on(sw):
                    targets.append(str(sw))
            elif otype in ("microwave", "fridge") and outlet.get("presence_auto_off"):
                sw = outlet.get("plug1_switch")
                if self._switch_entity_is_on(sw):
                    targets.append(str(sw))
        return list(dict.fromkeys(targets))

    def _keep_on_bindings(self, room: dict) -> list[str]:
        """switch.* IDs with keep-on enabled for a room."""
        bindings: list[str] = []
        for outlet in room.get("outlets", []):
            otype = outlet.get("type", "outlet")
            if otype == "outlet":
                if outlet.get("keep_on_plug1"):
                    sw = outlet.get("plug1_switch")
                    if self._is_switch_entity_id(sw):
                        bindings.append(str(sw))
                if outlet.get("keep_on_plug2"):
                    sw = outlet.get("plug2_switch")
                    if self._is_switch_entity_id(sw):
                        bindings.append(str(sw))
            elif otype == "light" and outlet.get("keep_on"):
                sw = outlet.get("switch_entity")
                if self._is_switch_entity_id(sw):
                    bindings.append(str(sw))
            elif otype in ("vent", "wall_heater") and outlet.get("keep_on"):
                sw = outlet.get("switch_entity")
                if self._is_switch_entity_id(sw):
                    bindings.append(str(sw))
            elif otype in ("single_outlet", "minisplit", "stove") and outlet.get(
                "keep_on"
            ):
                sw = outlet.get("plug1_switch")
                if self._is_switch_entity_id(sw):
                    bindings.append(str(sw))
            elif otype in ("microwave", "fridge") and outlet.get("keep_on"):
                sw = outlet.get("plug1_switch")
                if self._is_switch_entity_id(sw):
                    bindings.append(str(sw))
        return list(dict.fromkeys(bindings))

    def _keep_on_configured_switch_ids(self, room: dict) -> list[str]:
        return self._keep_on_bindings(room)

    def _presence_auto_off_blocks_keep_on(
        self, room: dict, room_id: str, switch_id: str
    ) -> bool:
        """True when presence auto-off owns this switch being off (defer keep-on)."""
        if switch_id not in self._presence_auto_off_configured_switch_ids(room):
            return False
        person_ent = room.get("presence_person_entity")
        zones = room.get("presence_zone_entities") or []
        if not person_ent or not zones:
            return False
        pending = self._presence_auto_turned_off.get(room_id)
        if pending and switch_id in pending:
            return True
        if self._room_presence_was_in_comfort.get(room_id) is False:
            return True
        return False

    def _keep_on_suppressed(self, room: dict, room_id: str, switch_id: str) -> bool:
        if self._presence_auto_off_blocks_keep_on(room, room_id, switch_id):
            return True
        if switch_id in self._integration_internal_switch_ids:
            return True
        if not self._entity_usable(switch_id):
            return True
        if switch_id in self._plug_shutoff_switch_entities:
            return True
        if self._room_in_enforcement_power_cycle(room_id):
            return True
        hold = self._minisplit_hold.get(room_id)
        if hold and switch_id in hold.get("switches", set()):
            return True
        outlet = self._find_outlet_by_switch(room, switch_id)
        if outlet:
            oname = outlet.get("name") or "Outlet"
            if outlet.get("plug1_switch") == switch_id:
                if self._shutoff_pending.get(f"{room_id}_{oname}_Plug 1"):
                    return True
            elif outlet.get("plug2_switch") == switch_id:
                if self._shutoff_pending.get(f"{room_id}_{oname}_Plug 2"):
                    return True
        return False

    async def _maybe_keep_on_switch(self, room: dict, switch_id: str) -> None:
        room_id = room.get("id", room["name"].lower().replace(" ", "_"))
        if self._keep_on_suppressed(room, room_id, switch_id):
            return
        if self._switch_entity_is_on(switch_id):
            return
        try:
            await self._async_switch_set(switch_id, True)
            _LOGGER.info(
                "Keep on: turned on %s (room %s)",
                switch_id,
                room_id,
            )
        except Exception as e:
            _LOGGER.warning("Keep on failed for %s: %s", switch_id, e)

    async def _tick_keep_on_switches(self) -> None:
        for room in self.config_manager.energy_config.get("rooms", []):
            for switch_id in self._keep_on_bindings(room):
                await self._maybe_keep_on_switch(room, switch_id)

    async def _keep_on_on_switch_turned_off(self, event: Event) -> None:
        entity_id = event.data.get("entity_id")
        new_state = event.data.get("new_state")
        old_state = event.data.get("old_state")
        if not entity_id or not new_state or new_state.state != "off":
            return
        if old_state and old_state.state == "off":
            return
        for room in self.config_manager.energy_config.get("rooms", []):
            for switch_id in self._keep_on_bindings(room):
                if switch_id == entity_id:
                    await self._maybe_keep_on_switch(room, switch_id)
                    return

    def _presence_room_lock(self, room_id: str) -> asyncio.Lock:
        if room_id not in self._presence_room_locks:
            self._presence_room_locks[room_id] = asyncio.Lock()
        return self._presence_room_locks[room_id]

    async def _presence_turn_off_room_switches(
        self, room: dict, room_id: str, *, reason: str
    ) -> None:
        pending = self._presence_auto_turned_off.setdefault(room_id, set())
        for sw in self._presence_auto_off_switch_targets(room):
            if sw in pending:
                continue
            try:
                await self._async_switch_set(sw, False)
                pending.add(sw)
                _LOGGER.info(
                    "Presence auto-off: turned off %s (room %s %s)",
                    sw,
                    room_id,
                    reason,
                )
                outlet = self._find_outlet_by_switch(room, sw)
                if outlet and outlet.get("type") == "minisplit":
                    outlet_name = outlet.get("name") or "Air Conditioner"
                    await self._send_notification_to_room_person(
                        room,
                        "ac_auto_off",
                        {"room_name": room.get("name", room_id), "outlet_name": outlet_name},
                        "Air Conditioner Off",
                        DEFAULT_NOTIFY_AC_AUTO_OFF_MSG,
                        integration_auto=True,
                    )
            except Exception as e:
                _LOGGER.warning("Presence auto-off failed for %s: %s", sw, e)

    async def _presence_restore_room_switches(self, room: dict, room_id: str) -> None:
        allowed = set(self._presence_auto_off_configured_switch_ids(room))
        pending = self._presence_auto_turned_off.get(room_id)
        if not pending:
            return
        pending &= allowed
        if not pending:
            self._presence_auto_turned_off.pop(room_id, None)
            return
        restored_switch_ids: list[str] = []
        for sw in list(pending):
            if self._switch_entity_is_on(sw):
                pending.discard(sw)
                continue
            try:
                await self._async_switch_set(sw, True)
                pending.discard(sw)
                restored_switch_ids.append(sw)
                _LOGGER.info(
                    "Presence auto-restore: turned on %s (room %s entered configured zones)",
                    sw,
                    room_id,
                )
                outlet = self._find_outlet_by_switch(room, sw)
                if outlet and outlet.get("type") == "minisplit":
                    outlet_name = outlet.get("name") or "Air Conditioner"
                    await self._send_notification_to_room_person(
                        room,
                        "ac_auto_on",
                        {"room_name": room.get("name", room_id), "outlet_name": outlet_name},
                        "Air Conditioner On",
                        DEFAULT_NOTIFY_AC_AUTO_ON_MSG,
                        integration_auto=True,
                    )
            except Exception as e:
                _LOGGER.warning("Presence auto-restore failed for %s: %s", sw, e)
        if restored_switch_ids:
            await self._async_speak_presence_restore_tts_for_room(
                room, restored_switch_ids
            )
        if not pending:
            self._presence_auto_turned_off.pop(room_id, None)

    async def _apply_presence_auto_off_for_room(self, room: dict) -> None:
        """On zone transitions only: turn off when leaving; restore once when returning."""
        room_id = room.get("id", room["name"].lower().replace(" ", "_"))
        async with self._presence_room_lock(room_id):
            person_ent = room.get("presence_person_entity")
            zones = room.get("presence_zone_entities") or []
            if not person_ent or not zones:
                self._room_presence_was_in_comfort.pop(room_id, None)
                self._presence_auto_turned_off.pop(room_id, None)
                return
            zone_ids = [str(z).strip() for z in zones if z and str(z).strip()]
            in_comfort = person_in_room_presence_zones(self.hass, person_ent, zone_ids)
            prev = self._room_presence_was_in_comfort.get(room_id)

            if prev is not None and prev == in_comfort:
                return

            self._room_presence_was_in_comfort[room_id] = in_comfort

            if prev is None:
                if not in_comfort:
                    await self._presence_turn_off_room_switches(
                        room, room_id, reason="startup outside zones"
                    )
                return

            if prev is True and not in_comfort:
                await self._presence_turn_off_room_switches(
                    room, room_id, reason="left zones"
                )
            elif prev is False and in_comfort:
                await self._presence_restore_room_switches(room, room_id)

    async def _presence_on_tracked_entity(self, entity_id: str | None) -> None:
        if not entity_id:
            return
        for room in self.config_manager.energy_config.get("rooms", []):
            pe = room.get("presence_person_entity")
            zs = room.get("presence_zone_entities") or []
            if not pe or not zs:
                continue
            trackers = get_person_device_tracker_entity_ids(self.hass, pe)
            if entity_id == pe or entity_id in zs or entity_id in trackers:
                await self._apply_presence_auto_off_for_room(room)

    def refresh_presence_listeners(self) -> None:
        """Teardown and re-register person/zone listeners (e.g. after config save)."""
        for unsub in self._presence_listener_unsub:
            try:
                unsub()
            except Exception:
                pass
        self._presence_listener_unsub = []
        self._setup_presence_listeners()
        self._setup_manual_toggle_switch_listeners()
        for room in self.config_manager.energy_config.get("rooms", []):
            self.hass.async_create_task(self._apply_presence_auto_off_for_room(room))

    def refresh_door_window_listeners(self) -> None:
        """Teardown and re-register door/window/lock/presence/contact listeners.

        Called from ``config_manager.async_update_energy`` after a config save
        so newly added doors/windows/contact sensors/locks/presence sensors
        start firing immediately, and removed ones stop. Previously config save
        only refreshed presence listeners, so the door/window listeners stayed
        bound to the old entity set until the integration was reloaded
        (audit BUG 1 — root cause of "door/window controls don't respond").
        """
        self._teardown_door_window_listeners()
        # Re-seed the baseline state dict so the first event after a refresh is
        # not absorbed as a duplicate (audit BUG 6 re-arm path).
        self._door_window_last_signal_state.clear()
        self._setup_door_window_listeners()

    def _setup_presence_listeners(self) -> None:
        track_ids: set[str] = set()
        switch_ids: set[str] = set()
        for room in self.config_manager.energy_config.get("rooms", []):
            pe = room.get("presence_person_entity")
            zs = room.get("presence_zone_entities") or []
            if pe and zs:
                track_ids.add(pe)
                for tracker in get_person_device_tracker_entity_ids(self.hass, pe):
                    track_ids.add(tracker)
                for z in zs:
                    if z and str(z).startswith("zone."):
                        track_ids.add(str(z))
            for sw in self._presence_auto_off_configured_switch_ids(room):
                if sw:
                    switch_ids.add(sw)
            for sw in self._keep_on_configured_switch_ids(room):
                if sw:
                    switch_ids.add(sw)

        if track_ids:
            @callback
            def _on_tracked(event: Event) -> None:
                eid = event.data.get("entity_id")
                self.hass.async_create_task(self._presence_on_tracked_entity(eid))

            unsub = async_track_state_change_event(
                self.hass,
                list(track_ids),
                _on_tracked,
            )
            self._presence_listener_unsub.append(unsub)

        if switch_ids:
            @callback
            def _on_switch_change(event: Event) -> None:
                self.hass.async_create_task(self._presence_on_switch_turned_on(event))
                self.hass.async_create_task(self._keep_on_on_switch_turned_off(event))

            unsub = async_track_state_change_event(
                self.hass,
                list(switch_ids),
                _on_switch_change,
            )
            self._presence_listener_unsub.append(unsub)

    async def _presence_on_switch_turned_on(self, event: Event) -> None:
        """Turn off switches immediately if they're turned on while person is outside zones."""
        entity_id = event.data.get("entity_id")
        new_state = event.data.get("new_state")
        old_state = event.data.get("old_state")

        if not new_state or new_state.state != "on":
            return
        if old_state and old_state.state == "on":
            return

        for room in self.config_manager.energy_config.get("rooms", []):
            person_ent = room.get("presence_person_entity")
            zones = room.get("presence_zone_entities") or []
            if not person_ent or not zones:
                continue

            configured_switches = set(self._presence_auto_off_configured_switch_ids(room))
            if entity_id not in configured_switches:
                continue

            if entity_id in self._integration_internal_switch_ids:
                continue

            zone_ids = [str(z).strip() for z in zones if z and str(z).strip()]
            if person_in_room_presence_zones(self.hass, person_ent, zone_ids):
                continue

            room_id = room.get("id", room["name"].lower().replace(" ", "_"))
            pending = self._presence_auto_turned_off.setdefault(room_id, set())

            try:
                await self._async_switch_set(entity_id, False)
                pending.add(entity_id)
                _LOGGER.info(
                    "Presence auto-off: immediately turned off %s (room %s, person outside configured zones)",
                    entity_id,
                    room_id,
                )
                outlet = self._find_outlet_by_switch(room, entity_id)
                if outlet and outlet.get("type") == "minisplit":
                    outlet_name = outlet.get("name") or "Air Conditioner"
                    await self._send_notification_to_room_person(
                        room,
                        "ac_auto_off",
                        {"room_name": room.get("name", room_id), "outlet_name": outlet_name},
                        "Air Conditioner Off",
                        DEFAULT_NOTIFY_AC_AUTO_OFF_MSG,
                        integration_auto=True,
                    )
            except Exception as e:
                _LOGGER.warning("Presence auto-off (switch listener) failed for %s: %s", entity_id, e)
            break

    async def async_start(self) -> None:
        """Start the energy monitoring loop and state-change listeners."""
        if self._running:
            return

        self._running = True
        self._register_zone_health_startup_listener()
        await self._async_load_budget_boost_slots()
        self._task = asyncio.create_task(self._monitor_loop())

        # Plug energy accumulated via poll loop every second (actual watts read each cycle).
        # State-change was removed: it missed switch current_power_w updates and caused undercounting.
        entity_ids = self._get_power_entity_ids()
        _LOGGER.info("Energy monitor started (poll-based accumulation for %d plug entities)", len(entity_ids))
        self._setup_presence_listeners()
        self._setup_manual_toggle_switch_listeners()
        self._setup_zone_health_listeners()
        self._setup_door_window_listeners()

        def _run_door_window_resync(_now: datetime | None = None) -> None:
            self.hass.async_create_task(
                self._async_resync_door_window_reminders_on_startup()
            )

        # Defer so entity states are stable (avoids false "open" / missed close after setup).
        if self.hass.state is CoreState.running:
            async_call_later(self.hass, timedelta(seconds=5), _run_door_window_resync)
        else:

            @callback
            def _after_ha_started(_event: Event | None = None) -> None:
                async_call_later(self.hass, timedelta(seconds=5), _run_door_window_resync)

            self.hass.bus.async_listen_once(
                EVENT_HOMEASSISTANT_STARTED, _after_ha_started
            )
        for room in self.config_manager.energy_config.get("rooms", []):
            await self._apply_presence_auto_off_for_room(room)

    def _teardown_manual_toggle_switch_listeners(self) -> None:
        for unsub in self._manual_toggle_listener_unsub:
            try:
                unsub()
            except Exception:
                pass
        self._manual_toggle_listener_unsub.clear()

    def _setup_manual_toggle_switch_listeners(self) -> None:
        """Notify all configured persons when a monitored switch changes (UI or automation)."""
        self._teardown_manual_toggle_switch_listeners()
        switch_ids = self._all_configured_outlet_switch_ids()
        if not switch_ids:
            return

        @callback
        def _on_switch(event: Event) -> None:
            self.hass.async_create_task(
                self._async_handle_manual_toggle_switch_event(event)
            )

        unsub = async_track_state_change_event(
            self.hass,
            list(switch_ids),
            _on_switch,
        )
        self._manual_toggle_listener_unsub.append(unsub)

    async def _async_handle_manual_toggle_switch_event(self, event: Event) -> None:
        """Universal manual-toggle push: all persons with a room assignment."""
        entity_id = event.data.get("entity_id")
        new_state = event.data.get("new_state")
        old_state = event.data.get("old_state")
        if not entity_id or not str(entity_id).startswith("switch."):
            return
        if old_state is None:
            return
        if not new_state or new_state.state not in ("on", "off"):
            return
        if old_state.state == new_state.state:
            return
        monitored = self._all_configured_outlet_switch_ids()
        if entity_id not in monitored:
            return
        if entity_id in self._plug_shutoff_switch_entities:
            return
        loc = self._room_outlet_context_for_switch_with_type(entity_id)
        if not loc:
            return
        room_id, room_name, outlet_display, _plug_slot, outlet_type = loc
        if self._room_in_enforcement_power_cycle(room_id):
            return

        now = dt_util.now()
        debounce_key = f"{entity_id}|{new_state.state}"
        last = self._manual_toggle_notify_last.get(debounce_key)
        if last and (now - last).total_seconds() < 1.5:
            return
        self._manual_toggle_notify_last[debounce_key] = now
        if len(self._manual_toggle_notify_last) > 200:
            self._manual_toggle_notify_last.clear()

        tts_settings = self.config_manager.energy_config.get("tts_settings") or {}
        if not tts_settings.get("notifications_enabled"):
            return

        user_name: str | None = None
        try:
            ctx = getattr(new_state, "context", None)
            uid = getattr(ctx, "user_id", None) if ctx is not None else None
            if uid:
                get_user = getattr(self.hass.auth, "async_get_user", None)
                if callable(get_user):
                    user = await get_user(uid)
                    if user is not None and getattr(user, "name", None):
                        user_name = str(user.name)
        except Exception:
            pass

        is_person = user_name is not None
        is_integration = entity_id in self._integration_internal_switch_ids
        if is_person:
            if not tts_settings.get("notify_person_toggle", True):
                return
            actor = user_name
        elif is_integration:
            if not tts_settings.get("notify_integration_auto", True):
                return
            # Gate wall_heater and vent integration toggles on their specific flags
            if outlet_type == "wall_heater" and not tts_settings.get("notify_heater_auto", True):
                return
            if outlet_type == "vent" and not tts_settings.get("notify_vent_auto", True):
                return
            actor = "Automation"
        else:
            if not tts_settings.get("notify_external_auto", True):
                return
            actor = "Automation"

        action = "on" if new_state.state == "on" else "off"
        await self._send_notification_broadcast(
            "toggle",
            {
                "user_name": actor,
                "room_name": room_name,
                "outlet_name": outlet_display,
                "action": action,
            },
            "Appliance Toggled",
            DEFAULT_NOTIFY_MANUAL_TOGGLE_MSG,
        )

    async def async_stop(self) -> None:
        """Stop the energy monitoring loop and listeners."""
        self._running = False
        for unsub in self._presence_listener_unsub:
            try:
                unsub()
            except Exception:
                pass
        self._presence_listener_unsub = []
        self._teardown_manual_toggle_switch_listeners()
        self._teardown_door_window_listeners()
        for unsub in self._power_listener_unsub:
            unsub()
        self._power_listener_unsub = []
        for unsub in self._person_zone_health_listener_unsub:
            try:
                unsub()
            except Exception:
                pass
        self._person_zone_health_listener_unsub = []
        # Cancel door reminder and auto-lock tasks
        for task in self._door_reminder_active.values():
            if task:
                task.cancel()
        self._door_reminder_active.clear()
        for task in self._door_auto_lock_task.values():
            if task:
                task.cancel()
        self._door_auto_lock_task.clear()
        # Cancel any in-flight presence hold-then-announce tasks (audit BUG 4).
        for task in self._presence_handler_tasks.values():
            if task:
                task.cancel()
        self._presence_handler_tasks.clear()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        _LOGGER.info("Energy monitor stopped")

    async def _monitor_loop(self) -> None:
        """Main monitoring loop - runs every second."""
        while self._running:
            try:
                await self._check_energy()
            except Exception:
                # Use _LOGGER.exception so the full traceback is preserved
                # (previously "%s" truncated it — Phase 3 HA-convention fix).
                _LOGGER.exception("Energy monitor error")

            await asyncio.sleep(ENERGY_CHECK_INTERVAL)

    async def _check_energy(self) -> None:
        """Check energy consumption for all rooms and outlets."""
        await self.config_manager.async_snapshot_day_and_reset_if_rolled_over()
        now = dt_util.now()
        today = now.strftime("%Y-%m-%d")
        if self._room_budget_announced_date != today:
            self._room_budget_announced.clear()
            self._room_budget_announced_date = today
        energy_config = self.config_manager.energy_config
        rooms = energy_config.get("rooms", [])
        tts_settings = energy_config.get("tts_settings", {})
        await self._maybe_fire_budget_boost_scheduled(now, today, tts_settings)

        for room in rooms:
            room_id = room.get("id", room["name"].lower().replace(" ", "_"))
            room_name = room["name"]
            room_threshold = room.get("threshold", 0)
            kwh_budget = float(room.get("kwh_budget", 5) or 5)
            room_uses_kwh_boost = room.get("kwh_budget_use_boost", True) is not False
            media_player = room.get("media_player")
            room_volume = room.get("volume", tts_settings.get("volume", 0.7))

            # Room budget: no warnings/shutoffs until room uses this much today (boost days scale budget).
            # Match dashboard: overBudget only when effKwh > 0 and usedKwh > effKwh (strict >).
            room_day_kwh = self.config_manager.get_room_day_kwh(room_id)
            effective_kwh_budget = self._effective_kwh_budget(
                kwh_budget,
                now,
                tts_settings,
                use_room_boost=room_uses_kwh_boost,
                room=room,
            )
            budget_exceeded = (
                effective_kwh_budget > 0 and room_day_kwh > effective_kwh_budget
            )

            # TTS when room first exceeds budget (once per day per room)
            if (
                budget_exceeded
                and kwh_budget > 0
                and media_player
                and room_id not in self._room_budget_announced
            ):
                self._room_budget_announced.add(room_id)
                if self._tts_line_enabled(tts_settings, "budget_exceeded"):
                    prefix = tts_settings.get("prefix", DEFAULT_TTS_PREFIX)
                    msg_template = tts_settings.get("budget_exceeded_msg") or DEFAULT_BUDGET_EXCEEDED_MSG
                    try:
                        message = msg_template.format(
                            prefix=prefix,
                            room_name=room_name,
                            kwh_used=spoken_cardinal(round(room_day_kwh)),
                        )
                        await self._async_send_tts_with_lights(
                            room, media_player, message, room_volume, tts_settings
                        )
                    except (KeyError, ValueError) as e:
                        _LOGGER.warning("Budget exceeded message format failed for %s: %s", room_name, e)
                try:
                    await self._send_notification_to_room_person(
                        room,
                        "budget_hit",
                        {
                            "room_name": room_name,
                            "kwh_budget": str(round(effective_kwh_budget, 1)),
                            "kwh_used": str(round(room_day_kwh, 1)),
                        },
                        "Budget Exceeded",
                        f"{room_name} has exceeded its daily budget of {round(effective_kwh_budget, 1)} kWh (used {round(room_day_kwh, 1)} kWh)",
                        integration_auto=True,
                    )
                except Exception as e:
                    _LOGGER.warning("Budget exceeded notification failed for %s: %s", room_name, e)

            weekdays_res = resolve_budget_boost_weekdays(room, tts_settings)
            room_mult = room.get("room_budget_boost_multiplier")
            eff_mult = float(room_mult) if room_mult is not None else float(tts_settings.get("budget_boost_multiplier") or 1)
            # First eligible pass after monitor start sends immediately (last_rem None); then hourly until weekdays set.
            wants_boost_days_reminder = (
                bool(room.get("presence_person_entity"))
                and room_uses_kwh_boost
                and kwh_budget > 0
                and bool(tts_settings.get("budget_boost_enabled"))
                and eff_mult > 1
                and not weekdays_res
            )
            if wants_boost_days_reminder:
                last_rem = self._room_boost_days_last_reminder_at.get(room_id)
                due = last_rem is None or (
                    now - last_rem
                ).total_seconds() >= ROOM_BOOST_DAYS_REMINDER_INTERVAL_SECONDS
                _LOGGER.debug(
                    "room_boost_days room_id=%s room_name=%s weekdays=%s last_reminder=%s due=%s",
                    room_id,
                    room_name,
                    weekdays_res,
                    last_rem,
                    due,
                )
                if due:
                    _LOGGER.debug(
                        "room_boost_days: sending notification for room_id=%s",
                        room_id,
                    )
                    try:
                        await self._send_notification_to_room_person(
                            room,
                            "room_boost_days",
                            {"room_name": room_name},
                            "Set boost days",
                            f"{room_name}: Open Home Energy and tap your room icon to choose up to two days when your higher kWh budget applies.",
                            integration_auto=False,
                        )
                        self._room_boost_days_last_reminder_at[room_id] = now
                    except Exception as e:
                        _LOGGER.warning(
                            "Boost days reminder notification failed for %s: %s",
                            room_name,
                            e,
                        )
            else:
                self._room_boost_days_last_reminder_at.pop(room_id, None)

            # Calculate total room watts and track energy
            room_total_watts = 0.0
            
            for outlet in room.get("outlets", []):
                outlet_name = outlet.get("name", "Outlet")
                outlet_threshold = outlet.get("threshold", 0)
                outlet_total_watts = 0.0

                # Light outlets: configured watts from map, or power_sensor_entity when switch on
                if outlet.get("type") == "light":
                    switch_entity = outlet.get("switch_entity")
                    power_ent = (
                        outlet.get("power_sensor_entity")
                        if outlet.get("power_source") == "sensor"
                        else None
                    )
                    if switch_entity:
                        state = self.hass.states.get(switch_entity)
                        is_on = state is not None and (state.state or "off").lower() in ("on",)
                        if is_on:
                            if power_ent:
                                outlet_total_watts = self._get_power_value(power_ent)
                                await self.config_manager.async_add_energy_reading(
                                    power_ent, outlet_total_watts, elapsed_seconds=1.0
                                )
                                self.config_manager.record_intraday_power(
                                    power_ent, outlet_total_watts
                                )
                            else:
                                light_ents = outlet.get("light_entities") or []
                                for le in light_ents:
                                    eid, _, _ = _normalize_light_entity_row(le)
                                    if not eid:
                                        continue
                                    w = (
                                        float(le.get("watts", 0) or 0)
                                        if isinstance(le, dict)
                                        else 0.0
                                    )
                                    outlet_total_watts += w
                                if outlet_total_watts > 0:
                                    tracking_key = f"light_{room_id}_{(outlet.get('name') or 'light').lower().replace(' ', '_')}"
                                    await self.config_manager.async_add_energy_reading(
                                        tracking_key, outlet_total_watts
                                    )
                                    self.config_manager.record_intraday_power(
                                        tracking_key, outlet_total_watts
                                    )
                    room_total_watts += outlet_total_watts
                    continue

                # Vent / wall heater: power sensor reads directly (like AC), or static watts when switch on
                if outlet.get("type") in ("vent", "wall_heater"):
                    switch_entity = outlet.get("switch_entity")
                    power_ent = (
                        outlet.get("power_sensor_entity")
                        if outlet.get("power_source") == "sensor"
                        else None
                    )
                    watts_when_on = float(outlet.get("watts_when_on", 0) or 0)
                    if power_ent:
                        # Power sensor mode: read sensor directly (sensor reports 0W when off)
                        outlet_total_watts = self._get_power_value(power_ent)
                        await self.config_manager.async_add_energy_reading(
                            power_ent, outlet_total_watts, elapsed_seconds=1.0
                        )
                        self.config_manager.record_intraday_power(
                            power_ent, outlet_total_watts
                        )
                    elif switch_entity:
                        # Fixed watts mode: use watts_when_on only when switch is on
                        state = self.hass.states.get(switch_entity)
                        is_on = state is not None and (state.state or "off").lower() in ("on",)
                        if is_on and watts_when_on > 0:
                            outlet_total_watts = watts_when_on
                            tracking_key = vent_like_energy_tracking_key(
                                room_id, outlet
                            )
                            await self.config_manager.async_add_energy_reading(
                                tracking_key, outlet_total_watts
                            )
                            self.config_manager.record_intraday_power(
                                tracking_key, outlet_total_watts
                            )
                    room_total_watts += outlet_total_watts
                    await self._tick_vent_automation(room, room_id, outlet, now)
                    await self._tick_wall_heater_automation(room, room_id, outlet, now)
                    # Check outlet warning threshold (only when budget exceeded)
                    if budget_exceeded and outlet_threshold > 0 and outlet_total_watts > outlet_threshold:
                        await self._send_outlet_alert(
                            room_id=room_id,
                            room_name=room_name,
                            room=room,
                            outlet_name=outlet_name,
                            current_watts=outlet_total_watts,
                            outlet_threshold=outlet_threshold,
                            media_player=media_player,
                            volume=room_volume,
                            tts_settings=tts_settings,
                        )
                    continue

                # Generic outlets: power_sensor_entity (matches statistics sources) + plug1/plug2, dedupe entity ids
                seen_oe: set[str] = set()
                pe = (outlet.get("power_sensor_entity") or "").strip()
                if pe:
                    seen_oe.add(pe)
                    w_pe = self._get_power_value(pe)
                    outlet_total_watts += w_pe
                    self.config_manager.record_intraday_power(pe, w_pe)
                    await self.config_manager.async_add_energy_reading(pe, w_pe, elapsed_seconds=1.0)

                plug1_watts = 0.0
                if outlet.get("plug1_entity"):
                    p1 = str(outlet["plug1_entity"]).strip()
                    if p1 not in seen_oe:
                        seen_oe.add(p1)
                        plug1_watts = self._get_power_value(outlet["plug1_entity"])
                        outlet_total_watts += plug1_watts
                        self.config_manager.record_intraday_power(outlet["plug1_entity"], plug1_watts)
                        await self.config_manager.async_add_energy_reading(
                            outlet["plug1_entity"], plug1_watts, elapsed_seconds=1.0
                        )

                    plug1_shutoff = outlet.get("plug1_shutoff", 0)
                    plug1_switch = outlet.get("plug1_switch")
                    if budget_exceeded and plug1_shutoff > 0 and plug1_watts > plug1_shutoff and plug1_switch:
                        await self._handle_plug_shutoff(
                            room_id=room_id,
                            room_name=room_name,
                            room=room,
                            outlet_name=outlet_name,
                            plug_name="Plug 1",
                            switch_entity=plug1_switch,
                            media_player=media_player,
                            volume=room_volume,
                            tts_settings=tts_settings,
                            plug_watts=plug1_watts,
                            plug_shutoff_threshold=int(plug1_shutoff),
                        )

                plug2_watts = 0.0
                if outlet.get("plug2_entity"):
                    p2 = str(outlet["plug2_entity"]).strip()
                    if p2 not in seen_oe:
                        seen_oe.add(p2)
                        plug2_watts = self._get_power_value(outlet["plug2_entity"])
                        outlet_total_watts += plug2_watts
                        self.config_manager.record_intraday_power(outlet["plug2_entity"], plug2_watts)
                        await self.config_manager.async_add_energy_reading(
                            outlet["plug2_entity"], plug2_watts, elapsed_seconds=1.0
                        )

                    plug2_shutoff = outlet.get("plug2_shutoff", 0)
                    plug2_switch = outlet.get("plug2_switch")
                    if budget_exceeded and plug2_shutoff > 0 and plug2_watts > plug2_shutoff and plug2_switch:
                        await self._handle_plug_shutoff(
                            room_id=room_id,
                            room_name=room_name,
                            room=room,
                            outlet_name=outlet_name,
                            plug_name="Plug 2",
                            switch_entity=plug2_switch,
                            media_player=media_player,
                            volume=room_volume,
                            tts_settings=tts_settings,
                            plug_watts=plug2_watts,
                            plug_shutoff_threshold=int(plug2_shutoff),
                        )

                room_total_watts += outlet_total_watts

                # Check outlet warning threshold (combined plugs, only when budget exceeded)
                if budget_exceeded and outlet_threshold > 0 and outlet_total_watts > outlet_threshold:
                    await self._send_outlet_alert(
                        room_id=room_id,
                        room_name=room_name,
                        room=room,
                        outlet_name=outlet_name,
                        current_watts=outlet_total_watts,
                        outlet_threshold=outlet_threshold,
                        media_player=media_player,
                        volume=room_volume,
                        tts_settings=tts_settings,
                    )

            await self._maybe_restore_minisplit_hold(
                room_id=room_id,
                room_name=room_name,
                room_total_watts=room_total_watts,
                room_threshold=float(room_threshold or 0),
                media_player=media_player,
                volume=room_volume,
                tts_settings=tts_settings,
            )

            # Check room threshold (only when budget exceeded)
            if budget_exceeded and room_threshold > 0 and room_total_watts > room_threshold:
                await self._send_room_alert(
                    room_id=room_id,
                    room_name=room_name,
                    room=room,
                    current_watts=room_total_watts,
                    media_player=media_player,
                    volume=room_volume,
                    tts_settings=tts_settings,
                )

        # Check breaker lines
        await self._check_breaker_lines(tts_settings)

        # Check stove safety
        await self._check_stove_safety(tts_settings)

        # Check power enforcement phase resets and kWh warnings
        await self._check_power_enforcement(tts_settings)

        # Check zone health (hourly)
        await self._async_tick_zone_health_check(now)

        # Check light automations (runs every tick)
        await self._tick_light_automation(now)

        # Keep-on switches (runs every tick)
        await self._tick_keep_on_switches()

        # Periodically save energy tracking data (every 15 seconds, survives restarts)
        self._save_counter += 1
        if self._save_counter >= 15:
            self._save_counter = 0
            await self.config_manager.async_save_persistent_data()

    def _get_power_value(self, entity_id: str) -> float:
        """Get power value from an entity in Watts."""
        state = self.hass.states.get(entity_id)
        if state is None:
            return 0.0

        # Sensor entity - power is the state value
        if entity_id.startswith("sensor."):
            try:
                if state.state not in ("unknown", "unavailable", ""):
                    val = float(state.state)
                    unit = state.attributes.get("unit_of_measurement")
                    if unit == "kW":
                        return val * 1000.0
                    if unit == "mW":
                        return val / 1000.0
                    return val  # W or default
            except (ValueError, TypeError):
                pass
            return 0.0

        # Switch entity - power is an attribute (already in W)
        if entity_id.startswith("switch."):
            power = state.attributes.get("current_power_w", 0)
            try:
                return float(power)
            except (ValueError, TypeError):
                return 0.0

        return 0.0

    def _get_room_by_id(self, room_id: str) -> dict | None:
        """Latest room dict from config (by id or slug from name)."""
        for r in self.config_manager.energy_config.get("rooms", []):
            rid = r.get("id", r["name"].lower().replace(" ", "_"))
            if rid == room_id:
                return r
        return None

    def _sum_room_total_watts_only(self, room: dict) -> float:
        """Current room total watts without energy accounting side effects."""
        room_total_watts = 0.0
        for outlet in room.get("outlets", []):
            outlet_total_watts = 0.0
            if outlet.get("type") == "light":
                switch_entity = outlet.get("switch_entity")
                power_ent = (
                    outlet.get("power_sensor_entity")
                    if outlet.get("power_source") == "sensor"
                    else None
                )
                if switch_entity:
                    state = self.hass.states.get(switch_entity)
                    is_on = state is not None and (state.state or "off").lower() in ("on",)
                    if is_on:
                        if power_ent:
                            outlet_total_watts = self._get_power_value(power_ent)
                        else:
                            for le in outlet.get("light_entities") or []:
                                eid, _, _ = _normalize_light_entity_row(le)
                                if not eid:
                                    continue
                                w = (
                                    float(le.get("watts", 0) or 0)
                                    if isinstance(le, dict)
                                    else 0.0
                                )
                                outlet_total_watts += w
                room_total_watts += outlet_total_watts
                continue
            if outlet.get("type") in ("vent", "wall_heater"):
                switch_entity = outlet.get("switch_entity")
                power_ent = (
                    outlet.get("power_sensor_entity")
                    if outlet.get("power_source") == "sensor"
                    else None
                )
                watts_when_on = float(outlet.get("watts_when_on", 0) or 0)
                if switch_entity:
                    state = self.hass.states.get(switch_entity)
                    is_on = state is not None and (state.state or "off").lower() in ("on",)
                    if is_on:
                        if power_ent:
                            outlet_total_watts = self._get_power_value(power_ent)
                        elif watts_when_on > 0:
                            outlet_total_watts = watts_when_on
                room_total_watts += outlet_total_watts
                continue
            if outlet.get("plug1_entity"):
                outlet_total_watts += self._get_power_value(outlet["plug1_entity"])
            if outlet.get("plug2_entity"):
                outlet_total_watts += self._get_power_value(outlet["plug2_entity"])
            room_total_watts += outlet_total_watts
        return room_total_watts

    def _sum_all_rooms_watts_only(self) -> float:
        """Sum current watts across all rooms without energy accounting side effects."""
        total_watts = 0.0
        rooms = self.config_manager.energy_config.get("rooms") or []
        for room in rooms:
            total_watts += self._sum_room_total_watts_only(room)
        return total_watts

    def _select_minisplit_enforcement_target(
        self, room: dict, current_watts: float, room_threshold: float
    ) -> dict | None:
        """Pick one minisplit outlet if it can clear the room threshold when turned off."""
        thr = float(room_threshold or 0)
        if thr <= 0:
            return None
        best: dict | None = None
        best_w = -1.0
        for outlet in room.get("outlets", []):
            if outlet.get("type") != "minisplit":
                continue
            sw = outlet.get("plug1_switch")
            if not sw or not str(sw).startswith("switch."):
                continue
            state = self.hass.states.get(sw)
            is_on = state is not None and (state.state or "off").lower() in ("on",)
            if not is_on:
                continue
            plug_ent = outlet.get("plug1_entity")
            w = self._get_power_value(plug_ent) if plug_ent else 0.0
            min_w = int(outlet.get("minisplit_enforcement_min_watts", 0) or 0)
            if min_w > 0 and w < min_w:
                continue
            if current_watts - w > thr:
                continue
            if w > best_w:
                best_w = w
                best = outlet
        return best

    def _format_minisplit_phase2_warn(
        self,
        tts_settings: dict,
        prefix: str,
        room_name: str,
        ms_outlet: dict,
        warning_count_spoken: str,
        room_threshold: float | int,
    ) -> str:
        tmpl = (tts_settings.get("minisplit_phase2_warn_msg") or "").strip()
        if not tmpl:
            tmpl = DEFAULT_MINISPLIT_PHASE2_WARN_MSG
        off_sec = int(ms_outlet.get("minisplit_enforcement_off_seconds", 60) or 60)
        try:
            return tmpl.format(
                prefix=prefix,
                room_name=room_name,
                outlet_name=ms_outlet.get("name") or "Mini-split",
                warning_count=warning_count_spoken,
                restore_delay=spoken_cardinal(off_sec),
                room_threshold=spoken_cardinal(int(room_threshold or 0)),
            )
        except (KeyError, ValueError):
            return ""

    async def _maybe_restore_minisplit_hold(
        self,
        room_id: str,
        room_name: str,
        room_total_watts: float,
        room_threshold: float,
        media_player: str | None,
        volume: float,
        tts_settings: dict,
    ) -> None:
        """Turn held mini-split(s) back on when room total is at or under threshold."""
        if room_id not in self._minisplit_hold:
            return
        if room_threshold <= 0:
            return
        if room_total_watts > room_threshold:
            return
        hold = self._minisplit_hold.pop(room_id)
        switches = hold.get("switches") or set()
        outlet_name = hold.get("outlet_name") or "Mini-split"
        eff_vol = float(hold.get("volume", volume))
        prefix = tts_settings.get("prefix", DEFAULT_TTS_PREFIX)
        try:
            for sw in switches:
                if sw and str(sw).startswith("switch."):
                    await self.hass.services.async_call(
                        "switch", "turn_on", {"entity_id": sw}, blocking=True
                    )
            _LOGGER.info(
                "Minisplit hold released (room under threshold): %s switches=%s",
                room_id,
                switches,
            )
        except Exception as e:
            _LOGGER.error("Minisplit hold restore failed: %s", e)
            return
        rest_tmpl = (tts_settings.get("minisplit_phase2_restore_msg") or "").strip()
        if not media_player or not rest_tmpl:
            return
        if not self._tts_line_enabled(tts_settings, "minisplit_phase2_restore"):
            return
        try:
            rmsg = rest_tmpl.format(
                prefix=prefix,
                room_name=room_name,
                outlet_name=outlet_name,
                room_threshold=spoken_cardinal(int(room_threshold)),
            )
            await async_send_tts_or_queue(
                self.hass,
                media_player=media_player,
                message=rmsg,
                language=tts_settings.get("language"),
                volume=eff_vol,
                tts_settings=tts_settings,
            )
        except (KeyError, ValueError) as e:
            _LOGGER.warning("Minisplit restore TTS format failed: %s", e)

    async def _run_phase2_minisplit_enforcement(
        self,
        room_id: str,
        room_name: str,
        room: dict,
        ms_outlet: dict,
        media_player: str | None,
        volume: float,
        tts_settings: dict,
        prefix: str,
        phase2_delay: int,
        *,
        cycle_log_extra: dict | None = None,
    ) -> None:
        """Minisplit-first phase-2: off, min wait, optional excluded full-room cycle, conditional restore."""
        sw = ms_outlet.get("plug1_switch")
        if not sw or not str(sw).startswith("switch."):
            await self._power_cycle_room_outlets(
                room_id, room, phase2_delay, log_extra=cycle_log_extra
            )
            return

        off_sec = int(ms_outlet.get("minisplit_enforcement_off_seconds", 60) or 60)
        outlet_name = ms_outlet.get("name") or "Mini-split"
        room_name_log = str(room.get("name") or room_id)

        self._enforcement_cycle_enter(room_id)
        try:
            merged_cycle = {**(cycle_log_extra or {})}
            merged_cycle["outlets_cycled"] = 1
            await self.config_manager.async_record_power_cycle_initiated(
                room_id, room_name_log, extra=merged_cycle
            )
            await self.hass.services.async_call(
                "switch", "turn_off", {"entity_id": sw}, blocking=True
            )
            _LOGGER.warning(
                "Phase-2 minisplit enforcement: turned off %s in %s",
                sw,
                room_id,
            )
            if room_id in self._minisplit_hold:
                self._minisplit_hold[room_id]["switches"].add(sw)
            else:
                self._minisplit_hold[room_id] = {
                    "switches": {sw},
                    "outlet_name": outlet_name,
                    "volume": volume,
                }

            await asyncio.sleep(off_sec)

            room_live = self._get_room_by_id(room_id) or room
            total = self._sum_room_total_watts_only(room_live)
            thr = float(room_live.get("threshold") or 0)
            hold_sw = frozenset(
                self._minisplit_hold.get(room_id, {}).get("switches", set())
            )
            if total > thr and hold_sw:
                await self._power_cycle_room_outlets(
                    room_id,
                    room_live,
                    phase2_delay,
                    exclude_switch_entities=hold_sw,
                    record_cycle=False,
                )

            hold_oname = self._minisplit_hold.get(room_id, {}).get(
                "outlet_name", outlet_name
            )
            after_tmpl = (tts_settings.get("minisplit_phase2_after_msg") or "").strip()
            if not after_tmpl:
                after_tmpl = (tts_settings.get("phase2_after_msg") or "").strip()
            if not after_tmpl:
                after_tmpl = DEFAULT_MINISPLIT_PHASE2_AFTER_MSG
            if media_player:
                use_ms_after = bool(
                    (tts_settings.get("minisplit_phase2_after_msg") or "").strip()
                )
                after_line = (
                    "minisplit_phase2_after" if use_ms_after else "phase2_after"
                )
                try:
                    after_msg = after_tmpl.format(
                        prefix=prefix,
                        room_name=room_name,
                        outlet_name=hold_oname,
                        room_threshold=spoken_cardinal(int(thr)),
                    )
                except (KeyError, ValueError):
                    after_msg = ""
                if after_msg and self._tts_line_enabled(tts_settings, after_line):
                    await async_send_tts_or_queue(
                        self.hass,
                        media_player=media_player,
                        message=after_msg,
                        language=tts_settings.get("language"),
                        volume=volume,
                        tts_settings=tts_settings,
                    )

            room_live = self._get_room_by_id(room_id) or room_live
            total = self._sum_room_total_watts_only(room_live)
            thr = float(room_live.get("threshold") or 0)
            if room_id in self._minisplit_hold and thr > 0 and total <= thr:
                hold = self._minisplit_hold.pop(room_id)
                for s in hold.get("switches", set()):
                    if s and str(s).startswith("switch."):
                        await self.hass.services.async_call(
                            "switch", "turn_on", {"entity_id": s}, blocking=True
                        )
                rest_tmpl = (tts_settings.get("minisplit_phase2_restore_msg") or "").strip()
                if (
                    media_player
                    and rest_tmpl
                    and self._tts_line_enabled(tts_settings, "minisplit_phase2_restore")
                ):
                    try:
                        rmsg = rest_tmpl.format(
                            prefix=prefix,
                            room_name=room_name,
                            outlet_name=hold.get("outlet_name", outlet_name),
                            room_threshold=spoken_cardinal(int(thr)),
                        )
                        await async_send_tts_or_queue(
                            self.hass,
                            media_player=media_player,
                            message=rmsg,
                            language=tts_settings.get("language"),
                            volume=volume,
                            tts_settings=tts_settings,
                        )
                    except (KeyError, ValueError) as e:
                        _LOGGER.warning("Minisplit immediate restore TTS failed: %s", e)
        except Exception as e:
            _LOGGER.error("Phase-2 minisplit enforcement failed: %s", e)
        finally:
            self._enforcement_cycle_exit(room_id)

    async def _handle_plug_shutoff(
        self,
        room_id: str,
        room_name: str,
        room: dict,
        outlet_name: str,
        plug_name: str,
        switch_entity: str,
        media_player: str | None,
        volume: float,
        tts_settings: dict,
        *,
        plug_watts: float | None = None,
        plug_shutoff_threshold: int | None = None,
    ) -> None:
        """Handle plug shutoff when threshold exceeded - turn off, wait 5s, turn back on."""
        shutoff_key = f"{room_id}_{outlet_name}_{plug_name}"
        
        # Don't re-trigger if already in shutoff cycle
        if self._shutoff_pending.get(shutoff_key):
            return
        
        self._shutoff_pending[shutoff_key] = True
        self._plug_shutoff_switch_entities.add(switch_entity)

        try:
            # Turn off the switch
            await self.hass.services.async_call(
                "switch", "turn_off",
                {"entity_id": switch_entity},
                blocking=True,
            )
            _LOGGER.warning(
                "Plug shutoff triggered: %s %s %s",
                room_name, outlet_name, plug_name,
            )
            
            # Send TTS message (with optional responsive light loop)
            if media_player:
                prefix = tts_settings.get("prefix", DEFAULT_TTS_PREFIX)
                msg_template = tts_settings.get("shutoff_msg", DEFAULT_SHUTOFF_MSG)
                message = msg_template.format(
                    prefix=prefix,
                    room_name=room_name,
                    outlet_name=outlet_name,
                    plug=plug_name,
                )
                room_live = self._get_room_by_id(room_id) or room
                room_sum = self._sum_room_total_watts_only(room_live)
                shutoff_extra: dict = {
                    "tts_message": message,
                    "volume_percent": int(round(volume * 100)),
                    "room_watts": int(round(room_sum)),
                }
                if plug_watts is not None:
                    shutoff_extra["outlet_watts"] = int(round(plug_watts))
                if plug_shutoff_threshold is not None:
                    shutoff_extra["outlet_threshold"] = int(plug_shutoff_threshold)
                try:
                    if self._tts_line_enabled(tts_settings, "shutoff"):
                        await self._async_send_tts_with_lights(
                            room, media_player, message, volume, tts_settings
                        )
                    # Count only when TTS was actually sent
                    await self.config_manager.async_increment_shutoff(room_id)
                    await self.config_manager.async_add_event_log_entry(
                        room_id,
                        room_name,
                        "shutoff",
                        outlet_name,
                        True,
                        extra=shutoff_extra,
                    )
                except Exception as tts_err:
                    _LOGGER.error("Shutoff TTS error: %s", tts_err)
                    await self.config_manager.async_add_event_log_entry(
                        room_id,
                        room_name,
                        "shutoff",
                        outlet_name,
                        False,
                        extra=shutoff_extra,
                    )
            
            # Wait 5 seconds
            await asyncio.sleep(SHUTOFF_RESET_DELAY)
            
            # Turn back on
            await self.hass.services.async_call(
                "switch", "turn_on",
                {"entity_id": switch_entity},
                blocking=True,
            )
            _LOGGER.info(
                "Plug reset after shutoff: %s %s %s",
                room_name, outlet_name, plug_name,
            )
        except Exception as e:
            _LOGGER.error("Plug shutoff error: %s", e)
        finally:
            self._shutoff_pending[shutoff_key] = False
            self._plug_shutoff_switch_entities.discard(switch_entity)

    def _get_wrgb_light_entities(self, room: dict) -> list[str]:
        """Get all WRGB light entity IDs for a room."""
        entities: list[str] = []
        for outlet in room.get("outlets", []):
            if outlet.get("type") != "light":
                continue
            for le in outlet.get("light_entities") or []:
                eid, wrgb, _ = _normalize_light_entity_row(le)
                if eid and wrgb:
                    entities.append(eid)
        return list(dict.fromkeys(entities))

    def _get_light_restore_data(self, entity_ids: list[str]) -> dict[str, dict]:
        """Get current light state for restore after warning loop.
        Stores only the mode-appropriate attribute: RGB mode -> rgb_color,
        temp mode -> color_temp_kelvin. Never both (one restore call per light)."""
        restore: dict[str, dict] = {}
        for eid in entity_ids:
            state = self.hass.states.get(eid)
            if state is None:
                continue
            attrs = state.attributes or {}
            is_on = (state.state or "off").lower() == "on"
            data: dict = {"was_on": is_on}
            color_mode = (attrs.get("color_mode") or "").lower()
            # RGB mode: store rgb_color only
            if color_mode in ("rgb", "hs", "xy") and "rgb_color" in attrs:
                data["rgb_color"] = list(attrs["rgb_color"])
            # Temp mode: store color_temp_kelvin or color_temp only
            elif color_mode == "color_temp":
                if "color_temp_kelvin" in attrs:
                    data["color_temp_kelvin"] = attrs["color_temp_kelvin"]
                elif "color_temp" in attrs:
                    data["color_temp"] = attrs["color_temp"]
            # Fallback when color_mode missing: prefer rgb if present, else temp
            elif "rgb_color" in attrs:
                data["rgb_color"] = list(attrs["rgb_color"])
            elif "color_temp_kelvin" in attrs:
                data["color_temp_kelvin"] = attrs["color_temp_kelvin"]
            elif "color_temp" in attrs:
                data["color_temp"] = attrs["color_temp"]
            restore[eid] = data
        return restore

    async def _async_light_warning_loop(
        self,
        entity_ids: list[str],
        rgb_color: list[int],
        temp_kelvin: int,
        tts_task: asyncio.Task,
        interval: float = 1.5,
    ) -> None:
        """Loop light color/temp changes until TTS task completes."""
        try:
            while not tts_task.done():
                await self.hass.services.async_call(
                    "light",
                    "turn_on",
                    {"entity_id": entity_ids, "rgb_color": rgb_color},
                    blocking=True,
                )
                await asyncio.sleep(interval)
                if tts_task.done():
                    break
                await self.hass.services.async_call(
                    "light",
                    "turn_on",
                    {"entity_id": entity_ids, "color_temp_kelvin": temp_kelvin},
                    blocking=True,
                )
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            _LOGGER.error("Light warning loop error: %s", e)

    async def _async_restore_lights(
        self,
        entity_ids: list[str],
        restore_data: dict[str, dict],
    ) -> None:
        """Restore lights to their pre-warning state."""
        for eid in entity_ids:
            data = restore_data.get(eid)
            if not data:
                continue
            try:
                was_on = data.get("was_on", True)
                if not was_on:
                    await self.hass.services.async_call(
                        "light", "turn_off", {"entity_id": eid}, blocking=True
                    )
                    continue
                # Restore color/temp for lights that were on
                restore_attrs = {k: v for k, v in data.items() if k != "was_on" and v is not None}
                await self.hass.services.async_call(
                    "light",
                    "turn_on",
                    {"entity_id": eid, **restore_attrs} if restore_attrs else {"entity_id": eid},
                    blocking=True,
                )
            except Exception as e:
                _LOGGER.warning("Failed to restore light %s: %s", eid, e)

    async def _async_send_tts_with_lights(
        self,
        room: dict,
        media_player: str | None,
        message: str,
        volume: float,
        tts_settings: dict,
        post_send_callback=None,
    ) -> None:
        """Send TTS and optionally run responsive light loop. Waits for media player ready (on/idle/standby).
        post_send_callback runs after TTS is actually sent (incl. when dequeued from queue)."""
        if not media_player:
            return

        async def _do_lights_and_tts() -> None:
            wrgb_lights = self._get_wrgb_light_entities(room) if room.get("responsive_light_warnings") else []
            rgb = room.get("responsive_light_color") or [245, 0, 0]
            temp_k = int(room.get("responsive_light_temp", 6500))
            interval = float(room.get("responsive_light_interval", 1.5))
            if wrgb_lights:
                restore_data = self._get_light_restore_data(wrgb_lights)
                tts_task = asyncio.create_task(
                    async_send_tts(
                        self.hass,
                        media_player=media_player,
                        message=message,
                        language=tts_settings.get("language"),
                        volume=volume,
                    )
                )
                light_task = asyncio.create_task(
                    self._async_light_warning_loop(wrgb_lights, rgb, temp_k, tts_task, interval)
                )
                # Restore lights in a finally so they are not stuck in the warning
                # color when TTS fails (audit BUG 10).
                try:
                    await asyncio.gather(tts_task, light_task)
                except Exception as e:
                    _LOGGER.warning("Responsive-light TTS gather failed: %s", e)
                finally:
                    await self._async_restore_lights(wrgb_lights, restore_data)
            else:
                await async_send_tts(
                    self.hass,
                    media_player=media_player,
                    message=message,
                    language=tts_settings.get("language"),
                    volume=volume,
                )

        await async_send_tts_or_queue(
            self.hass,
            media_player=media_player,
            message=message,
            language=tts_settings.get("language"),
            volume=volume,
            tts_settings=tts_settings,
            room=room,
            with_lights_callback=_do_lights_and_tts,
            post_send_callback=post_send_callback,
        )

    def _get_room_for_breaker(self, breaker_id: str) -> dict | None:
        """Get first room with responsive lights and outlets on this breaker."""
        outlets = self.config_manager.get_outlets_for_breaker(breaker_id)
        room_ids = list(dict.fromkeys(o["room_id"] for o in outlets))
        for room in self.config_manager.energy_config.get("rooms", []):
            if room.get("id") in room_ids and room.get("responsive_light_warnings"):
                if self._get_wrgb_light_entities(room):
                    return room
        return None

    async def _async_room_enforcement_after_threshold_recorded(
        self,
        *,
        room_id: str,
        room_name: str,
        room: dict,
        current_watts: float,
        media_player: str | None,
        volume: float,
        tts_settings: dict,
        include_standard_room_warn: bool = True,
    ) -> tuple[float, str, object | None, bool]:
        """Phase/volume TTS, optional room-threshold wording, and phase-2 cycle callback after a recorded warning."""
        daily_warnings = self.config_manager.get_event_counts().get("room_warnings", {}).get(
            room_id, 0
        )
        tts_warning_cardinal = spoken_cardinal(daily_warnings + 1)

        pe = self.config_manager.energy_config.get("power_enforcement", {})
        enforcement_enabled = self.config_manager.is_room_enforcement_enabled(room_id)
        room_threshold = room.get("threshold", 0)

        effective_volume = volume
        message = ""
        prefix = tts_settings.get("prefix", DEFAULT_TTS_PREFIX)

        if enforcement_enabled:
            state = self.config_manager.get_enforcement_state(room_id)
            phase1_count = pe.get("phase1_warning_count", 20)
            phase1_window = pe.get("phase1_time_window_minutes", 60)
            phase2_count = pe.get("phase2_warning_count", 40)
            phase2_window = pe.get("phase2_time_window_minutes", 30)
            volume_increment = pe.get("phase1_volume_increment", 2)
            phase2_enabled = pe.get("phase2_enabled", True)

            warnings_in_phase1_window = self.config_manager.get_warnings_in_window(
                room_id, phase1_window
            )
            warnings_in_phase2_window = self.config_manager.get_warnings_in_window(
                room_id, phase2_window
            )

            phase = int(state.get("phase", 0) or 0)

            if phase2_enabled and warnings_in_phase2_window >= phase2_count and phase < 2:
                await self.config_manager.async_set_enforcement_phase(room_id, 2)
                await self._send_notification_to_room_person(
                    room,
                    "enforcement_phase2",
                    {"room_name": room_name},
                    "Enforcement Phase 2",
                    f"{room_name} has entered enforcement phase 2 (power cycling). Please reduce power usage.",
                    integration_auto=True,
                )
                ms_o = self._select_minisplit_enforcement_target(
                    room, float(current_watts), float(room_threshold or 0)
                )
                if ms_o and self._tts_line_enabled(tts_settings, "minisplit_phase2_warn"):
                    message = self._format_minisplit_phase2_warn(
                        tts_settings,
                        prefix,
                        room_name,
                        ms_o,
                        tts_warning_cardinal,
                        room_threshold,
                    )
                if not message and self._tts_line_enabled(tts_settings, "phase2_warn"):
                    msg_template = tts_settings.get("phase2_warn_msg") or ""
                    try:
                        message = msg_template.format(
                            prefix=prefix,
                            room_name=room_name,
                            warning_count=tts_warning_cardinal,
                        )
                    except (KeyError, ValueError):
                        message = ""

            elif pe.get("phase1_enabled", True) and warnings_in_phase1_window >= phase1_count and phase < 1:
                await self.config_manager.async_set_enforcement_phase(room_id, 1)
                await self._send_notification_to_room_person(
                    room,
                    "enforcement_phase1",
                    {"room_name": room_name},
                    "Enforcement Phase 1",
                    f"{room_name} has entered enforcement phase 1 (volume escalation). Please reduce power usage.",
                    integration_auto=True,
                )
                now_p1 = dt_util.now()
                boost_tmpl = (tts_settings.get("phase1_warn_msg_boost_day") or "").strip()
                room_uses_kwh_boost = room.get("kwh_budget_use_boost", True) is not False
                if (
                    ConfigManager._is_budget_boost_day(now_p1, tts_settings, room)
                    and boost_tmpl
                    and room_uses_kwh_boost
                    and self._tts_line_enabled(tts_settings, "phase1_warn_boost_day")
                ):
                    base_b = float(room.get("kwh_budget", 5) or 5)
                    eff_b = self._effective_kwh_budget(
                        base_b,
                        now_p1,
                        tts_settings,
                        use_room_boost=True,
                        room=room,
                    )
                    room_mult = room.get("room_budget_boost_multiplier") if room else None
                    if room_mult is not None:
                        mult = float(room_mult)
                    else:
                        mult = float(tts_settings.get("budget_boost_multiplier") or 2)
                    mult_s = self._budget_multiplier_tts_str(max(1.0, min(5.0, mult)))
                    weekdays = resolve_budget_boost_weekdays(room, tts_settings)
                    period = self._budget_boost_period_label(weekdays)
                    try:
                        message = boost_tmpl.format(
                            prefix=prefix,
                            room_name=room_name,
                            warning_count=tts_warning_cardinal,
                            threshold=spoken_cardinal(
                                int(room_threshold) if room_threshold is not None else 0
                            ),
                            kwh_budget=spoken_cardinal(round(base_b)),
                            kwh_budget_effective=spoken_cardinal(round(eff_b)),
                            budget_multiplier=mult_s,
                            period_label=period,
                        )
                    except (KeyError, ValueError):
                        message = ""
                else:
                    message = ""
                if not message and self._tts_line_enabled(tts_settings, "phase1_warn"):
                    msg_template = tts_settings.get("phase1_warn_msg") or ""
                    try:
                        message = msg_template.format(
                            prefix=prefix,
                            room_name=room_name,
                            warning_count=tts_warning_cardinal,
                            threshold=spoken_cardinal(
                                int(room_threshold) if room_threshold is not None else 0
                            ),
                        )
                    except (KeyError, ValueError):
                        message = ""

            phase = int(self.config_manager.get_enforcement_state(room_id).get("phase", 0) or 0)
            if (
                enforcement_enabled
                and phase2_enabled
                and phase >= 2
                and warnings_in_phase2_window >= phase2_count
                and not message
            ):
                ms_o = self._select_minisplit_enforcement_target(
                    room, float(current_watts), float(room_threshold or 0)
                )
                if ms_o and self._tts_line_enabled(tts_settings, "minisplit_phase2_warn"):
                    message = self._format_minisplit_phase2_warn(
                        tts_settings,
                        prefix,
                        room_name,
                        ms_o,
                        tts_warning_cardinal,
                        room_threshold,
                    )
                if not message and self._tts_line_enabled(tts_settings, "phase2_warn"):
                    msg_template = tts_settings.get("phase2_warn_msg") or ""
                    try:
                        message = msg_template.format(
                            prefix=prefix,
                            room_name=room_name,
                            warning_count=tts_warning_cardinal,
                        )
                    except (KeyError, ValueError):
                        message = ""

            phase = int(self.config_manager.get_enforcement_state(room_id).get("phase", 0) or 0)
            if phase >= 1:
                new_offset = await self.config_manager.async_increment_volume_offset(
                    room_id, volume_increment
                )
                effective_volume = min(1.0, volume + (new_offset / 100.0))
            if phase >= 2:
                phase2_max = pe.get("phase2_max_volume", 100)
                if phase2_max is not None:
                    cap = max(0.0, min(1.0, float(phase2_max) / 100.0))
                    effective_volume = min(effective_volume, cap)

        if (
            include_standard_room_warn
            and not message
            and self._tts_line_enabled(tts_settings, "room_warn")
        ):
            msg_template = tts_settings.get("room_warn_msg") or DEFAULT_ROOM_WARN_MSG
            try:
                message = msg_template.format(
                    prefix=prefix,
                    room_name=room_name,
                    watts=int(current_watts),
                    threshold=int(room_threshold) if room_threshold is not None else 0,
                )
            except (KeyError, ValueError):
                message = (
                    f"{prefix} {room_name} is using {int(current_watts)} watts out of "
                    f"{int(room_threshold or 0)} watt room threshold, reduce your usage."
                )

        post_send_cb = None
        if enforcement_enabled and pe.get("phase2_enabled", True):
            phase_now = int(
                self.config_manager.get_enforcement_state(room_id).get("phase", 0) or 0
            )
            if phase_now == 2:
                delay_sec = pe.get("phase2_cycle_delay_seconds", 5)
                after_template = tts_settings.get("phase2_after_msg") or ""
                ms_target = self._select_minisplit_enforcement_target(
                    room, float(current_watts), float(room_threshold or 0)
                )

                try:
                    rtc = int(room.get("threshold", 0) or 0)
                except (TypeError, ValueError):
                    rtc = 0
                cycle_log_extra = {
                    "tts_message": message,
                    "room_watts": int(round(current_watts)),
                    "room_threshold": rtc,
                    "enforcement_phase": phase_now,
                    "volume_percent": int(round(effective_volume * 100)),
                }

                async def _power_cycle_and_tts_after() -> None:
                    if ms_target:
                        await self._run_phase2_minisplit_enforcement(
                            room_id,
                            room_name,
                            room,
                            ms_target,
                            media_player,
                            effective_volume,
                            tts_settings,
                            prefix,
                            delay_sec,
                            cycle_log_extra=cycle_log_extra,
                        )
                    else:
                        await self._power_cycle_room_outlets(
                            room_id, room, delay_sec, log_extra=cycle_log_extra
                        )
                        if (
                            media_player
                            and after_template
                            and self._tts_line_enabled(tts_settings, "phase2_after")
                        ):
                            try:
                                after_msg = after_template.format(
                                    prefix=prefix,
                                    room_name=room_name,
                                )
                            except (KeyError, ValueError):
                                after_msg = (
                                    f"{prefix} Cycle complete in {room_name}. "
                                    "Stay under limit or outlets cycle again."
                                )
                            await async_send_tts_or_queue(
                                self.hass,
                                media_player=media_player,
                                message=after_msg,
                                language=tts_settings.get("language"),
                                volume=effective_volume,
                                tts_settings=tts_settings,
                            )

                post_send_cb = _power_cycle_and_tts_after

        return effective_volume, message, post_send_cb, enforcement_enabled

    async def _send_room_alert(
        self,
        room_id: str,
        room_name: str,
        room: dict,
        current_watts: float,
        media_player: str | None,
        volume: float,
        tts_settings: dict,
    ) -> None:
        """Send TTS alert for room threshold exceeded with power enforcement."""
        if not media_player:
            return

        # Phase transition (cooldown bypass): window count after this breach is +1; detect before record.
        now = dt_util.now()
        pe = self.config_manager.energy_config.get("power_enforcement", {})
        enforcement_enabled = self.config_manager.is_room_enforcement_enabled(room_id)
        phase1_enabled = pe.get("phase1_enabled", True)
        phase2_enabled = pe.get("phase2_enabled", True)
        phase_transition = False
        if enforcement_enabled:
            state = self.config_manager.get_enforcement_state(room_id)
            phase = int(state.get("phase", 0) or 0)
            phase1_count = pe.get("phase1_warning_count", 20)
            phase1_window = pe.get("phase1_time_window_minutes", 60)
            phase2_count = pe.get("phase2_warning_count", 40)
            phase2_window = pe.get("phase2_time_window_minutes", 30)
            warnings_p1 = self.config_manager.get_warnings_in_window(room_id, phase1_window)
            warnings_p2 = self.config_manager.get_warnings_in_window(room_id, phase2_window)
            phase_transition = (
                (phase2_enabled and warnings_p2 + 1 >= phase2_count and phase < 2)
                or (phase1_enabled and warnings_p1 + 1 >= phase1_count and phase < 1)
            )

        # Cooldown: skip for phase transitions (we always need TTS when phases enable)
        last_alert = self._last_room_alerts.get(room_id)
        if not phase_transition and last_alert and (now - last_alert).total_seconds() < ALERT_COOLDOWN:
            return  # Still in cooldown

        self._last_room_alerts[room_id] = now

        await self.config_manager.async_record_threshold_warning(room_id, current_watts)

        (
            effective_volume,
            message,
            post_send_cb,
            enforcement_enabled,
        ) = await self._async_room_enforcement_after_threshold_recorded(
            room_id=room_id,
            room_name=room_name,
            room=room,
            current_watts=current_watts,
            media_player=media_player,
            volume=volume,
            tts_settings=tts_settings,
            include_standard_room_warn=True,
        )

        msg_stripped = (message or "").strip()
        if not msg_stripped and post_send_cb is None:
            return

        try:
            rt_raw = room.get("threshold", 0)
            try:
                rt_int = int(rt_raw) if rt_raw is not None else 0
            except (TypeError, ValueError):
                rt_int = 0

            def _room_warning_log_extra() -> dict:
                ex: dict = {
                    "tts_message": message,
                    "room_watts": int(round(current_watts)),
                    "room_threshold": rt_int,
                    "volume_percent": int(round(effective_volume * 100)),
                }
                if enforcement_enabled:
                    ex["enforcement_phase"] = int(
                        self.config_manager.get_enforcement_state(room_id).get(
                            "phase", 0
                        )
                        or 0
                    )
                return ex

            if msg_stripped:
                await self._async_send_tts_with_lights(
                    room, media_player, message, effective_volume, tts_settings,
                    post_send_callback=post_send_cb,
                )
            elif post_send_cb:
                await post_send_cb()
            # Count only when TTS was actually sent
            await self.config_manager.async_increment_warning(room_id)
            await self.config_manager.async_add_event_log_entry(
                room_id,
                room_name,
                "warning",
                None,
                True,
                extra=_room_warning_log_extra(),
            )
            _LOGGER.warning(
                "Room threshold alert: %s - %dW (enforcement phase %d, volume %.0f%%)",
                room_name,
                int(current_watts),
                self.config_manager.get_enforcement_state(room_id).get("phase", 0) if enforcement_enabled else 0,
                effective_volume * 100,
            )
        except Exception as e:
            _LOGGER.error("Failed to send room threshold alert: %s", e)
            try:
                rt_raw = room.get("threshold", 0)
                rt_int = int(rt_raw) if rt_raw is not None else 0
            except (TypeError, ValueError):
                rt_int = 0
            fail_ex: dict = {
                "tts_message": message,
                "room_watts": int(round(current_watts)),
                "room_threshold": rt_int,
                "volume_percent": int(round(effective_volume * 100)),
            }
            if enforcement_enabled:
                fail_ex["enforcement_phase"] = int(
                    self.config_manager.get_enforcement_state(room_id).get("phase", 0)
                    or 0
                )
            await self.config_manager.async_add_event_log_entry(
                room_id,
                room_name,
                "warning",
                None,
                False,
                extra=fail_ex,
            )

    async def _power_cycle_room_outlets(
        self,
        room_id: str,
        room: dict,
        delay_seconds: int,
        *,
        exclude_switch_entities: frozenset[str] | None = None,
        record_cycle: bool = True,
        log_extra: dict | None = None,
    ) -> None:
        """Power cycle outlets with switches (stove/microwave excluded for safety)."""
        exclude = exclude_switch_entities or frozenset()
        switch_entities: list[str] = []
        seen: set[str] = set()
        for outlet in room.get("outlets", []):
            if outlet.get("type") in ("stove", "microwave"):
                continue
            for switch in (
                outlet.get("plug1_switch"),
                outlet.get("plug2_switch"),
                outlet.get("switch_entity"),
            ):
                if (
                    switch
                    and switch.startswith("switch.")
                    and switch not in seen
                    and switch not in exclude
                ):
                    seen.add(switch)
                    switch_entities.append(switch)

        if not switch_entities:
            _LOGGER.debug(
                "No switchable outlets in room %s for power cycle (after exclusions)",
                room_id,
            )
            return

        self._enforcement_cycle_enter(room_id)
        try:
            room_name = str(room.get("name") or room_id)
            if record_cycle:
                merged = {**(log_extra or {})}
                merged["outlets_cycled"] = len(switch_entities)
                await self.config_manager.async_record_power_cycle_initiated(
                    room_id, room_name, extra=merged
                )
            _LOGGER.info(
                "Power cycling %d outlets in %s for enforcement",
                len(switch_entities),
                room_id,
            )
            await self.hass.services.async_call(
                "switch", "turn_off", {"entity_id": switch_entities}, blocking=True
            )
            await asyncio.sleep(delay_seconds)
            await self.hass.services.async_call(
                "switch", "turn_on", {"entity_id": switch_entities}, blocking=True
            )
            _LOGGER.warning(
                "Power cycled %d outlets in %s for enforcement",
                len(switch_entities),
                room_id,
            )
        except Exception as e:
            _LOGGER.error("Failed to power cycle outlets in %s: %s", room_id, e)
        finally:
            self._enforcement_cycle_exit(room_id)

    async def _send_outlet_alert(
        self,
        room_id: str,
        room_name: str,
        room: dict,
        outlet_name: str,
        current_watts: float,
        outlet_threshold: int,
        media_player: str | None,
        volume: float,
        tts_settings: dict,
    ) -> None:
        """Send TTS alert for outlet threshold exceeded."""
        if not media_player:
            return

        # Check cooldown - use combined room+outlet key
        alert_key = f"{room_id}_{outlet_name}"
        now = dt_util.now()
        last_alert = self._last_outlet_alerts.get(alert_key)
        if last_alert and (now - last_alert).total_seconds() < ALERT_COOLDOWN:
            return  # Still in cooldown

        # Update last alert time
        self._last_outlet_alerts[alert_key] = now

        # Record threshold warning for power enforcement (outlet warnings count toward room)
        await self.config_manager.async_record_threshold_warning(room_id, current_watts)

        # Format message with prefix
        prefix = tts_settings.get("prefix", DEFAULT_TTS_PREFIX)
        msg_template = tts_settings.get("outlet_warn_msg", DEFAULT_OUTLET_WARN_MSG)
        message = msg_template.format(
            prefix=prefix,
            room_name=room_name,
            outlet_name=outlet_name,
            watts=spoken_cardinal(current_watts),
            threshold=spoken_cardinal(outlet_threshold),
        )

        room_sum = self._sum_room_total_watts_only(room)

        def _outlet_warning_extra() -> dict:
            ox: dict = {
                "tts_message": message,
                "outlet_watts": int(round(current_watts)),
                "outlet_threshold": int(outlet_threshold),
                "room_watts": int(round(room_sum)),
                "volume_percent": int(round(volume * 100)),
            }
            if self.config_manager.is_room_enforcement_enabled(room_id):
                ox["enforcement_phase"] = int(
                    self.config_manager.get_enforcement_state(room_id).get("phase", 0)
                    or 0
                )
            return ox

        try:
            if self._tts_line_enabled(tts_settings, "outlet_warn"):
                await self._async_send_tts_with_lights(
                    room, media_player, message, volume, tts_settings
                )
            # Count only when TTS was actually sent
            await self.config_manager.async_increment_warning(room_id)
            await self.config_manager.async_add_event_log_entry(
                room_id,
                room_name,
                "warning",
                outlet_name,
                True,
                extra=_outlet_warning_extra(),
            )
            _LOGGER.warning(
                "Outlet threshold alert: %s %s - %dW",
                room_name,
                outlet_name,
                int(current_watts),
            )
        except Exception as e:
            _LOGGER.error("Failed to send outlet threshold alert: %s", e)
            await self.config_manager.async_add_event_log_entry(
                room_id,
                room_name,
                "warning",
                outlet_name,
                False,
                extra=_outlet_warning_extra(),
            )

    async def _check_power_enforcement(self, tts_settings: dict) -> None:
        """Check power enforcement phase resets and kWh warnings."""
        pe = self.config_manager.energy_config.get("power_enforcement", {})
        if not pe.get("enabled", False):
            return

        prefix = tts_settings.get("prefix", DEFAULT_TTS_PREFIX)
        rooms = self.config_manager.energy_config.get("rooms", [])
        rooms_enabled = pe.get("rooms_enabled", [])

        # Check phase resets for each room
        phase1_reset = pe.get("phase1_reset_minutes", 60)
        phase2_reset = pe.get("phase2_reset_minutes", 30)
        now_pe = dt_util.now()
        raw_kwh_intervals = pe.get("room_kwh_intervals", [5, 10, 15, 20])

        for room in rooms:
            room_id = room.get("id", room["name"].lower().replace(" ", "_"))
            room_name = room.get("name", room_id)
            media_player = room.get("media_player")
            volume = float(room.get("volume", 0.7))
            base_kwh_budget = float(room.get("kwh_budget", 5) or 5)
            room_uses_kwh_boost = room.get("kwh_budget_use_boost", True) is not False

            if room_id not in rooms_enabled:
                continue

            state = self.config_manager.get_enforcement_state(room_id)
            current_phase = state.get("phase", 0)

            # Check for phase reset (no warnings for reset_minutes)
            reset_minutes = phase2_reset if current_phase == 2 else phase1_reset
            if current_phase > 0 and self.config_manager.check_phase_reset(room_id, reset_minutes):
                await self.config_manager.async_set_enforcement_phase(room_id, 0)
                msg_template = tts_settings.get("phase_reset_msg", "")
                if (
                    msg_template
                    and media_player
                    and self._tts_line_enabled(tts_settings, "phase_reset")
                ):
                    message = msg_template.format(
                        prefix=prefix,
                        room_name=room_name,
                    )
                    try:
                        await self._async_send_tts_with_lights(
                            room, media_player, message, volume, tts_settings
                        )
                        _LOGGER.info("Power enforcement reset for %s", room_name)
                    except Exception as e:
                        _LOGGER.error("Failed to send phase reset TTS: %s", e)

            # Check room kWh intervals (same tier filter as dashboard bar / boost)
            filtered_intervals = self.config_manager.filter_room_kwh_intervals_for_alerts(
                raw_kwh_intervals,
                base_kwh_budget,
                now_pe,
                tts_settings,
                use_room_budget_boost=room_uses_kwh_boost,
                room=room,
            )
            interval_hit = None
            if filtered_intervals:
                interval_hit = await self.config_manager.async_should_send_room_kwh_alert(
                    room_id, filtered_intervals
                )
            if interval_hit is not None and media_player:
                percentage = self.config_manager.get_room_percentage_of_total(room_id)
                msg_template = tts_settings.get("room_kwh_warn_msg", "")
                if msg_template and self._tts_line_enabled(tts_settings, "room_kwh_warn"):
                    message = msg_template.format(
                        prefix=prefix,
                        room_name=room_name,
                        kwh_limit=interval_hit,
                        percentage=percentage,
                    )
                    try:
                        await self._async_send_tts_with_lights(
                            room, media_player, message, volume, tts_settings
                        )
                        _LOGGER.warning(
                            "Room kWh alert: %s exceeded %s kWh", room_name, interval_hit
                        )
                    except Exception as e:
                        _LOGGER.error("Failed to send room kWh alert: %s", e)

        # Check home kWh limit
        home_limit = pe.get("home_kwh_limit", 22)
        if await self.config_manager.async_should_send_home_kwh_alert(home_limit):
            # Find a media player to use
            media_player = None
            room_for_tts = None
            for room in rooms:
                if room.get("media_player"):
                    media_player = room["media_player"]
                    room_for_tts = room
                    break

            if media_player and room_for_tts:
                msg_template = tts_settings.get("home_kwh_warn_msg", "")
                if msg_template and self._tts_line_enabled(tts_settings, "home_kwh_warn"):
                    total_kwh = self.config_manager.get_total_day_kwh()
                    message = msg_template.format(
                        prefix=prefix,
                        kwh_limit=spoken_cardinal(home_limit),
                    )
                    try:
                        volume = float(room_for_tts.get("volume", 0.7))
                        await self._async_send_tts_with_lights(
                            room_for_tts, media_player, message, volume, tts_settings
                        )
                        _LOGGER.warning("Home kWh alert: exceeded %d kWh (current: %.1f)", home_limit, total_kwh)
                    except Exception as e:
                        _LOGGER.error("Failed to send home kWh alert: %s", e)

    async def _check_breaker_lines(self, tts_settings: dict) -> None:
        """Check breaker line loads and trigger warnings/shutoffs."""
        energy_config = self.config_manager.energy_config
        breaker_lines = energy_config.get("breaker_lines", [])
        
        for breaker in breaker_lines:
            breaker_id = breaker.get("id")
            breaker_name = breaker.get("name", "Breaker")
            max_load = breaker.get("max_load", 2400)
            threshold = breaker.get("threshold", 0)
            
            # Get all outlets on this breaker
            outlets = self.config_manager.get_outlets_for_breaker(breaker_id)
            
            # Calculate total power for this breaker
            breaker_total_watts = 0.0
            for outlet in outlets:
                if outlet.get("plug1_entity"):
                    breaker_total_watts += self._get_power_value(outlet["plug1_entity"])
                if outlet.get("plug2_entity"):
                    breaker_total_watts += self._get_power_value(outlet["plug2_entity"])
            
            # Get room for responsive lights (first room with outlets on this breaker and responsive lights)
            # Fallback: first room with media_player
            room_for_lights = self._get_room_for_breaker(breaker_id)
            media_player = None
            volume = tts_settings.get("volume", 0.7)
            if room_for_lights:
                media_player = room_for_lights.get("media_player")
                volume = float(room_for_lights.get("volume", 0.7))
            if not media_player:
                for room in energy_config.get("rooms", []):
                    if room.get("media_player"):
                        media_player = room["media_player"]
                        room_for_lights = room if room_for_lights is None else room_for_lights
                        break
            
            # Check warning threshold (near max)
            if threshold > 0 and breaker_total_watts >= threshold:
                # Check cooldown
                now = dt_util.now()
                last_warning = self._last_breaker_warnings.get(breaker_id)
                if not last_warning or (now - last_warning).total_seconds() >= ALERT_COOLDOWN:
                    self._last_breaker_warnings[breaker_id] = now
                    
                    prefix = tts_settings.get("prefix", DEFAULT_TTS_PREFIX)
                    msg_template = tts_settings.get("breaker_warn_msg", DEFAULT_BREAKER_WARN_MSG)
                    message = msg_template.format(
                        prefix=prefix,
                        breaker_name=breaker_name,
                        watts=int(breaker_total_watts),
                        max_load=max_load,
                    )
                    
                    if media_player:
                        if room_for_lights:
                            await self._async_send_tts_with_lights(
                                room_for_lights, media_player, message, volume, tts_settings
                            )
                        else:
                            await async_send_tts_or_queue(
                                self.hass,
                                media_player=media_player,
                                message=message,
                                language=tts_settings.get("language"),
                                volume=volume,
                            )
                    _LOGGER.warning("Breaker warning: %s - %dW", breaker_name, int(breaker_total_watts))
            
            # Check shutoff threshold (at max)
            if max_load > 0 and breaker_total_watts >= max_load:
                # Don't re-trigger if already in shutoff cycle
                if self._breaker_shutoff_pending.get(breaker_id):
                    continue
                
                # Check cooldown
                now = dt_util.now()
                last_shutoff = self._last_breaker_shutoffs.get(breaker_id)
                if last_shutoff and (now - last_shutoff).total_seconds() < ALERT_COOLDOWN:
                    continue
                
                self._breaker_shutoff_pending[breaker_id] = True
                self._last_breaker_shutoffs[breaker_id] = now
                
                try:
                    # Send TTS message (with optional responsive light loop)
                    prefix = tts_settings.get("prefix", DEFAULT_TTS_PREFIX)
                    msg_template = tts_settings.get("breaker_shutoff_msg", DEFAULT_BREAKER_SHUTOFF_MSG)
                    message = msg_template.format(
                        prefix=prefix,
                        breaker_name=breaker_name,
                        watts=spoken_cardinal(breaker_total_watts),
                        max_load=spoken_cardinal(max_load),
                    )
                    
                    if media_player:
                        if room_for_lights:
                            await self._async_send_tts_with_lights(
                                room_for_lights, media_player, message, volume, tts_settings
                            )
                        else:
                            await async_send_tts_or_queue(
                                self.hass,
                                media_player=media_player,
                                message=message,
                                language=tts_settings.get("language"),
                                volume=volume,
                            )
                    
                    # Turn off ALL switches for all outlets on this breaker
                    switch_entities = []
                    for outlet in outlets:
                        if outlet.get("plug1_switch") and outlet["plug1_switch"].startswith("switch."):
                            switch_entities.append(outlet["plug1_switch"])
                        if outlet.get("plug2_switch") and outlet["plug2_switch"].startswith("switch."):
                            switch_entities.append(outlet["plug2_switch"])
                    
                    if switch_entities:
                        # Turn off all switches
                        await self.hass.services.async_call(
                            "switch", "turn_off",
                            {"entity_id": switch_entities},
                            blocking=True,
                        )
                        _LOGGER.warning(
                            "Breaker shutoff triggered: %s - %dW, turned off %d switches",
                            breaker_name, int(breaker_total_watts), len(switch_entities)
                        )
                        
                        # Wait 5 seconds
                        await asyncio.sleep(SHUTOFF_RESET_DELAY)
                        
                        # Turn all switches back on
                        await self.hass.services.async_call(
                            "switch", "turn_on",
                            {"entity_id": switch_entities},
                            blocking=True,
                        )
                        _LOGGER.info(
                            "Breaker reset after shutoff: %s - %d switches turned back on",
                            breaker_name, len(switch_entities)
                        )
                except Exception as e:
                    _LOGGER.error("Breaker shutoff error: %s", e)
                finally:
                    self._breaker_shutoff_pending[breaker_id] = False

    def _get_stove_configs(self) -> list[tuple[str, dict, dict]]:
        """Get all configured stove devices with (room_id, stove_outlet, room)."""
        energy_config = self.config_manager.energy_config
        result = []
        for room in energy_config.get("rooms", []):
            room_id = room.get("id", room["name"].lower().replace(" ", "_"))
            for outlet in room.get("outlets", []):
                if outlet.get("type") == "stove":
                    result.append((room_id, outlet, room))
                    break
        return result

    def _get_microwave_stove_pairs(self) -> list[tuple[dict, dict, dict]]:
        """Get (microwave_outlet, stove_outlet, room) for rooms with both."""
        energy_config = self.config_manager.energy_config
        result = []
        for room in energy_config.get("rooms", []):
            outlets = room.get("outlets", [])
            stoves = [o for o in outlets if o.get("type") == "stove"]
            microwaves = [o for o in outlets if o.get("type") == "microwave"]
            if not stoves or not microwaves:
                continue
            stove = stoves[0]
            for mw in microwaves:
                if mw.get("plug1_entity") and stove.get("plug1_switch"):
                    result.append((mw, stove, room))
                    break
        return result

    async def _check_stove_safety(self, tts_settings: dict) -> None:
        """Check stove safety per device - monitor stove state, presence, microwave, and manage timers."""
        # Microwave safety first: cut stove when microwave on (shared breaker)
        # Requires both stove safety and microwave safety to be enabled
        for mw_outlet, stove_outlet, room in self._get_microwave_stove_pairs():
            if stove_outlet.get("stove_safety_enabled") is False:
                continue
            if mw_outlet.get("microwave_safety_enabled") is False:
                continue
            mw_entity = mw_outlet.get("plug1_entity")
            stove_switch = stove_outlet.get("plug1_switch")
            stove_entity = stove_outlet.get("plug1_entity")
            mw_threshold = int(mw_outlet.get("microwave_power_threshold", 50))
            media_player = room.get("media_player")
            volume = float(room.get("volume", 0.7))
            if not mw_entity or not stove_switch or not stove_entity:
                continue
            key = stove_entity
            self._stove_powered_off_by_microwave.setdefault(key, False)
            mw_power = self._get_power_value(mw_entity)
            stove_power = self._get_power_value(stove_entity)
            stove_threshold = int(stove_outlet.get("stove_power_threshold", 100))
            stove_is_on = stove_power > stove_threshold
            mw_is_on = mw_power > mw_threshold
            if mw_is_on and stove_is_on:
                if not self._stove_powered_off_by_microwave[key]:
                    self._stove_powered_off_by_microwave[key] = True
                    try:
                        await self.hass.services.async_call(
                            "switch", "turn_off",
                            {"entity_id": stove_switch},
                            blocking=True,
                        )
                        if media_player:
                            prefix = tts_settings.get("prefix", DEFAULT_TTS_PREFIX)
                            msg_template = tts_settings.get(
                                "microwave_cut_power_msg", DEFAULT_MICROWAVE_CUT_MSG
                            )
                            message = msg_template.format(prefix=prefix)
                            await self._async_send_tts_with_lights(
                                room, media_player, message, volume, tts_settings
                            )
                        _LOGGER.warning("Stove power cut: microwave is on (shared breaker)")
                    except Exception as e:
                        _LOGGER.error("Failed to cut stove for microwave: %s", e)
                        self._stove_powered_off_by_microwave[key] = False
            elif self._stove_powered_off_by_microwave[key] and not mw_is_on:
                try:
                    await self.hass.services.async_call(
                        "switch", "turn_on",
                        {"entity_id": stove_switch},
                        blocking=True,
                    )
                    if media_player:
                        prefix = tts_settings.get("prefix", DEFAULT_TTS_PREFIX)
                        msg_template = tts_settings.get(
                            "microwave_restore_power_msg", DEFAULT_MICROWAVE_RESTORE_MSG
                        )
                        message = msg_template.format(prefix=prefix)
                        await self._async_send_tts_with_lights(
                            room, media_player, message, volume, tts_settings
                        )
                    self._stove_powered_off_by_microwave[key] = False
                    self._stove_state[key] = "on"
                    _LOGGER.info("Stove power restored: microwave is off")
                except Exception as e:
                    _LOGGER.error("Failed to restore stove after microwave: %s", e)

        # Stove safety per stove device
        for _room_id, stove_outlet, room in self._get_stove_configs():
            stove_plug_entity = stove_outlet.get("plug1_entity")
            stove_plug_switch = stove_outlet.get("plug1_switch")
            presence_sensor = stove_outlet.get("presence_sensor")
            if not stove_plug_entity or not presence_sensor:
                continue
            key = stove_plug_entity
            self._stove_state.setdefault(key, "off")
            self._stove_timer_start.setdefault(key, None)
            self._stove_timer_phase.setdefault(key, "none")
            self._stove_last_presence.setdefault(key, None)
            self._stove_15min_warn_sent.setdefault(key, False)
            self._stove_30sec_warn_sent.setdefault(key, False)
            self._stove_powered_off_by_microwave.setdefault(key, False)
            self._stove_power_below_since.setdefault(key, None)
            self._stove_power_above_since.setdefault(key, None)
            self._stove_presence_window_start.setdefault(key, None)
            self._stove_progress_last_boundary.setdefault(key, 0)

            stove_power_threshold = int(stove_outlet.get("stove_power_threshold", 100))
            stove_off_debounce = int(stove_outlet.get("stove_off_debounce_seconds", 10))
            stove_on_debounce = int(stove_outlet.get("stove_on_debounce_seconds", 0))
            timer_start_window = int(stove_outlet.get("timer_start_window_seconds", 10))
            cooking_time_minutes = int(stove_outlet.get("cooking_time_minutes", 15))
            final_warning_seconds = int(stove_outlet.get("final_warning_seconds", 30))
            cooking_time_sec = max(1, cooking_time_minutes) * 60
            final_warning_sec = max(1, min(final_warning_seconds, 300))
            media_player = room.get("media_player")
            volume = float(room.get("volume", 0.7))

            current_power = self._get_power_value(stove_plug_entity)
            stove_is_on = current_power > stove_power_threshold
            if self._stove_powered_off_by_microwave[key]:
                continue

            presence_state = self.hass.states.get(presence_sensor)
            state_val = (presence_state.state or "").lower() if presence_state else ""
            presence_detected = state_val in ("detected", "on")
            now = dt_util.now()

            # Stove on/off with debounce (electric stoves fluctuate at medium heat)
            if stove_is_on:
                if self._stove_power_above_since[key] is None:
                    self._stove_power_above_since[key] = now
                self._stove_power_below_since[key] = None
                elapsed_above = (now - self._stove_power_above_since[key]).total_seconds()
                if self._stove_state[key] != "on" and elapsed_above >= stove_on_debounce:
                    self._stove_state[key] = "on"
                    self._stove_15min_warn_sent[key] = False
                    self._stove_30sec_warn_sent[key] = False
                    if media_player and self._tts_line_enabled(tts_settings, "stove_on"):
                        prefix = tts_settings.get("prefix", DEFAULT_TTS_PREFIX)
                        msg_template = tts_settings.get("stove_on_msg", DEFAULT_STOVE_ON_MSG)
                        await async_send_tts_or_queue(
                            self.hass, media_player=media_player, message=msg_template.format(prefix=prefix),
                            language=tts_settings.get("language"), volume=volume,
                        )
                    _LOGGER.info("Stove turned on")
            else:
                if self._stove_power_below_since[key] is None:
                    self._stove_power_below_since[key] = now
                self._stove_power_above_since[key] = None
                elapsed_below = (now - self._stove_power_below_since[key]).total_seconds()
                if self._stove_state[key] == "on" and elapsed_below >= stove_off_debounce:
                    self._stove_state[key] = "off"
                    self._stove_timer_start[key] = None
                    self._stove_timer_phase[key] = "none"
                    self._stove_presence_window_start[key] = None
                    self._stove_15min_warn_sent[key] = False
                    self._stove_30sec_warn_sent[key] = False
                    self._stove_progress_last_boundary[key] = 0
                    if (
                        not self._stove_powered_off_by_microwave[key]
                        and media_player
                        and self._tts_line_enabled(tts_settings, "stove_off")
                    ):
                        prefix = tts_settings.get("prefix", DEFAULT_TTS_PREFIX)
                        msg_template = tts_settings.get("stove_off_msg", DEFAULT_STOVE_OFF_MSG)
                        await async_send_tts_or_queue(
                            self.hass, media_player=media_player, message=msg_template.format(prefix=prefix),
                            language=tts_settings.get("language"), volume=volume,
                        )
                    _LOGGER.info("Stove turned off")

            if not stove_is_on:
                continue

            if presence_detected:
                self._stove_presence_window_start[key] = None
                if self._stove_timer_phase[key] != "none":
                    self._stove_timer_start[key] = None
                    self._stove_timer_phase[key] = "none"
                    self._stove_15min_warn_sent[key] = False
                    self._stove_30sec_warn_sent[key] = False
                    self._stove_progress_last_boundary[key] = 0
                    _LOGGER.info("Presence detected - timer reset")
                self._stove_last_presence[key] = "on"
            else:
                # Cooking timer: presence window before starting (don't start if person briefly left)
                window_start = self._stove_presence_window_start[key]
                if self._stove_last_presence[key] == "on":
                    if window_start is None:
                        self._stove_presence_window_start[key] = now
                    else:
                        window_elapsed = (now - window_start).total_seconds()
                        if window_elapsed >= timer_start_window:
                            self._stove_timer_start[key] = now
                            self._stove_timer_phase[key] = "15min"
                            self._stove_presence_window_start[key] = None
                            self._stove_15min_warn_sent[key] = False
                            self._stove_30sec_warn_sent[key] = False
                            if media_player and self._tts_line_enabled(tts_settings, "stove_timer_started"):
                                prefix = tts_settings.get("prefix", DEFAULT_TTS_PREFIX)
                                msg_template = tts_settings.get(
                                    "stove_timer_started_msg", DEFAULT_STOVE_TIMER_STARTED_MSG
                                )
                                await async_send_tts_or_queue(
                                    self.hass, media_player=media_player,
                                    message=msg_template.format(
                                        prefix=prefix,
                                        cooking_time_minutes=spoken_cardinal(cooking_time_minutes),
                                        final_warning_seconds=spoken_cardinal(final_warning_sec),
                                    ),
                                    language=tts_settings.get("language"), volume=volume,
                                )
                            _LOGGER.info("Presence left - starting cooking timer (%d min)", cooking_time_minutes)
                            self._stove_last_presence[key] = "off"

                if self._stove_timer_start[key]:
                    now = dt_util.now()
                    elapsed = (now - self._stove_timer_start[key]).total_seconds()
                    if self._stove_timer_phase[key] == "15min":
                        cfg_iv = int(stove_outlet.get("stove_timer_tts_interval_seconds", 0) or 0)
                        interval_sec = cfg_iv if cfg_iv > 0 else max(60, cooking_time_sec // 4)
                        if (
                            media_player
                            and interval_sec > 0
                            and elapsed < cooking_time_sec - 0.5
                            and self._tts_line_enabled(tts_settings, "stove_timer_progress")
                        ):
                            bnd = int(elapsed // interval_sec)
                            last_b = self._stove_progress_last_boundary.get(key, 0)
                            if bnd > last_b and bnd >= 1:
                                rem = max(0, int(cooking_time_sec - elapsed))
                                rm, rs = rem // 60, rem % 60
                                prefix = tts_settings.get("prefix", DEFAULT_TTS_PREFIX)
                                msg_tmpl = (
                                    tts_settings.get("stove_timer_progress_msg") or ""
                                ).strip() or DEFAULT_STOVE_TIMER_PROGRESS_MSG
                                room_name = room.get("name", "Kitchen")
                                try:
                                    message = msg_tmpl.format(
                                        prefix=prefix,
                                        room_name=room_name,
                                        minutes_remaining=spoken_cardinal(rm),
                                        seconds_remaining=spoken_cardinal(rs),
                                    )
                                    await self._async_send_tts_with_lights(
                                        room, media_player, message, volume, tts_settings
                                    )
                                except (KeyError, ValueError) as e:
                                    _LOGGER.warning("Stove timer progress TTS format failed: %s", e)
                                self._stove_progress_last_boundary[key] = bnd
                        if elapsed >= cooking_time_sec:
                            if not self._stove_15min_warn_sent[key]:
                                if media_player and self._tts_line_enabled(tts_settings, "stove_15min_warn"):
                                    prefix = tts_settings.get("prefix", DEFAULT_TTS_PREFIX)
                                    msg_template = tts_settings.get("stove_15min_warn_msg", DEFAULT_STOVE_15MIN_WARN_MSG)
                                    message = msg_template.format(
                                        prefix=prefix, cooking_time_minutes=cooking_time_minutes,
                                        final_warning_seconds=final_warning_sec,
                                    )
                                    await self._async_send_tts_with_lights(
                                        room, media_player, message, volume, tts_settings
                                    )
                                self._stove_15min_warn_sent[key] = True
                                _LOGGER.warning("Stove cooking-time warning - starting %ds countdown", final_warning_sec)
                            # When shutoff disabled, skip 30sec final warning (it's only relevant before shutoff)
                            if stove_outlet.get("stove_safety_enabled") is False:
                                self._stove_timer_start[key] = None
                                self._stove_timer_phase[key] = "none"
                                self._stove_15min_warn_sent[key] = False
                                self._stove_30sec_warn_sent[key] = False
                            else:
                                self._stove_timer_start[key] = now
                                self._stove_timer_phase[key] = "30sec"
                                self._stove_30sec_warn_sent[key] = False
                    elif self._stove_timer_phase[key] == "30sec":
                        if elapsed >= final_warning_sec:
                            if not self._stove_30sec_warn_sent[key]:
                                if media_player and self._tts_line_enabled(tts_settings, "stove_30sec_warn"):
                                    prefix = tts_settings.get("prefix", DEFAULT_TTS_PREFIX)
                                    msg_template = tts_settings.get("stove_30sec_warn_msg", DEFAULT_STOVE_30SEC_WARN_MSG)
                                    await async_send_tts_or_queue(
                                        self.hass, media_player=media_player,
                                        message=msg_template.format(
                                            prefix=prefix,
                                            cooking_time_minutes=spoken_cardinal(cooking_time_minutes),
                                            final_warning_seconds=spoken_cardinal(final_warning_sec),
                                        ),
                                        language=tts_settings.get("language"), volume=volume,
                                    )
                                self._stove_30sec_warn_sent[key] = True
                            # Only turn off stove if stove_safety_enabled; when off, TTS still plays but no shutoff
                            if stove_outlet.get("stove_safety_enabled") is not False and stove_plug_switch:
                                try:
                                    await self.hass.services.async_call(
                                        "switch", "turn_off",
                                        {"entity_id": stove_plug_switch},
                                        blocking=True,
                                    )
                                    if media_player and self._tts_line_enabled(tts_settings, "stove_auto_off"):
                                        prefix = tts_settings.get("prefix", DEFAULT_TTS_PREFIX)
                                        msg_template = tts_settings.get("stove_auto_off_msg", DEFAULT_STOVE_AUTO_OFF_MSG)
                                        message = msg_template.format(prefix=prefix)
                                        await self._async_send_tts_with_lights(
                                            room, media_player, message, volume, tts_settings
                                        )
                                    _LOGGER.warning("Stove automatically turned off for safety")
                                except Exception as e:
                                    _LOGGER.error("Failed to turn off stove: %s", e)
                            # Reset timer state in both cases (shutoff or TTS-only) to avoid re-triggering
                            self._stove_timer_start[key] = None
                            self._stove_timer_phase[key] = "none"
                            self._stove_15min_warn_sent[key] = False
                            self._stove_30sec_warn_sent[key] = False
                            self._stove_progress_last_boundary[key] = 0

    # -------------------------------------------------------------------------
    # Door / Window / Lock / Presence Automation
    # -------------------------------------------------------------------------

    def _teardown_door_window_listeners(self) -> None:
        """Remove door/window/lock/presence/battery state listeners."""
        for unsub in self._door_window_listener_unsub:
            try:
                unsub()
            except Exception:
                pass
        self._door_window_listener_unsub.clear()
        for unsub in self._lock_listener_unsub:
            try:
                unsub()
            except Exception:
                pass
        self._lock_listener_unsub.clear()
        for unsub in self._door_presence_listener_unsub:
            try:
                unsub()
            except Exception:
                pass
        self._door_presence_listener_unsub.clear()
        # Teardown battery listeners
        for unsub in self._battery_listener_unsub:
            try:
                unsub()
            except Exception:
                pass
        self._battery_listener_unsub.clear()
        self._door_window_last_signal_state.clear()

    def _setup_door_window_listeners(self) -> None:
        """Subscribe to door/window contact sensor, lock, and presence sensor state changes."""
        self._teardown_door_window_listeners()
        
        contact_sensor_ids: set[str] = set()
        lock_ids: set[str] = set()
        presence_sensor_ids: set[str] = set()
        
        for room in self.config_manager.energy_config.get("rooms", []):
            for outlet in room.get("outlets", []):
                otype = outlet.get("type")
                if otype in ("door", "window"):
                    cs = outlet.get("contact_sensor")
                    if cs and cs.startswith("binary_sensor."):
                        contact_sensor_ids.add(cs)
                    ps = outlet.get("presence_sensor")
                    if ps and ps.startswith("binary_sensor."):
                        presence_sensor_ids.add(ps)
                    if otype == "door":
                        lock = outlet.get("lock_entity")
                        if lock and lock.startswith("lock."):
                            lock_ids.add(lock)
        
        if contact_sensor_ids:
            @callback
            def _on_contact_change(event: Event) -> None:
                self.hass.async_create_task(
                    self._async_handle_contact_sensor_change(event)
                )
            unsub = async_track_state_change_event(
                self.hass, list(contact_sensor_ids), _on_contact_change
            )
            self._door_window_listener_unsub.append(unsub)
            _LOGGER.debug("Door/window contact listeners registered for %d sensors", len(contact_sensor_ids))
        
        if lock_ids:
            @callback
            def _on_lock_change(event: Event) -> None:
                self.hass.async_create_task(
                    self._async_handle_lock_state_change(event)
                )
            unsub = async_track_state_change_event(
                self.hass, list(lock_ids), _on_lock_change
            )
            self._lock_listener_unsub.append(unsub)
            _LOGGER.debug("Lock listeners registered for %d entities", len(lock_ids))
        
        if presence_sensor_ids:
            @callback
            def _on_door_presence_change(event: Event) -> None:
                self.hass.async_create_task(
                    self._async_handle_door_window_presence_change(event)
                )
            unsub = async_track_state_change_event(
                self.hass, list(presence_sensor_ids), _on_door_presence_change
            )
            self._door_presence_listener_unsub.append(unsub)
            _LOGGER.debug("Door/window presence listeners registered for %d sensors", len(presence_sensor_ids))

        def _seed_contact_lock_baselines() -> None:
            for eid in contact_sensor_ids:
                st = self.hass.states.get(eid)
                if st and st.state not in ("unknown", "unavailable", ""):
                    self._door_window_last_signal_state[eid] = str(st.state).strip()
            for eid in lock_ids:
                st = self.hass.states.get(eid)
                if st and st.state not in ("unknown", "unavailable", ""):
                    self._door_window_last_signal_state[eid] = str(st.state).strip()

        _seed_contact_lock_baselines()

        # Setup battery monitoring for door/window sensors
        self._setup_battery_listeners()

    async def _async_resync_door_window_reminders_on_startup(self) -> None:
        """Start reminder tasks when contact/lock is already open/unlocked (no transition on HA restart)."""
        if not self._running:
            return
        tts_settings = self.config_manager.energy_config.get("tts_settings", {}) or {}
        for room in self.config_manager.energy_config.get("rooms", []):
            media_player = room.get("media_player")
            volume = float(room.get("volume", 0.7) or 0.7)
            for outlet in room.get("outlets", []):
                otype = outlet.get("type")
                if otype == "door":
                    key = self._door_window_key(outlet, room)
                    contact = outlet.get("contact_sensor")
                    if (
                        outlet.get("reminder_mode") == "open"
                        and isinstance(contact, str)
                        and contact.startswith("binary_sensor.")
                    ):
                        st = self.hass.states.get(contact)
                        if (
                            st
                            and st.state not in ("unknown", "unavailable", "")
                            and self._contact_sensor_state_is_open(st.state)
                        ):
                            lock_ent_check = str(outlet.get("lock_entity") or "").strip()
                            skip_open = False
                            if lock_ent_check.startswith("lock."):
                                lchk = self.hass.states.get(lock_ent_check)
                                if lchk and lchk.state == "locked":
                                    skip_open = True
                            if not skip_open:
                                await self._start_door_reminder(
                                    outlet,
                                    room,
                                    key,
                                    "open",
                                    media_player,
                                    volume,
                                    tts_settings,
                                )
                                _LOGGER.debug(
                                    "Door reminder resync: started open reminder for %s (%s)",
                                    outlet.get("name") or key,
                                    contact,
                                )
                    lock = outlet.get("lock_entity")
                    if (
                        outlet.get("reminder_mode") == "unlocked"
                        and isinstance(lock, str)
                        and lock.startswith("lock.")
                    ):
                        lst = self.hass.states.get(lock)
                        if lst and lst.state not in ("unknown", "unavailable", ""):
                            if lst.state != "locked":
                                lock_key = f"{key}_lock"
                                await self._start_door_reminder(
                                    outlet,
                                    room,
                                    lock_key,
                                    "unlocked",
                                    media_player,
                                    volume,
                                    tts_settings,
                                )
                                _LOGGER.debug(
                                    "Door reminder resync: started unlocked reminder for %s (%s)",
                                    outlet.get("name") or key,
                                    lock,
                                )
                    # Re-arm auto-lock for a door that is currently closed and
                    # was closed before HA restarted. Without this the pending
                    # auto-lock is lost on restart and the door stays unlocked
                    # until the next open/close cycle (audit BUG 6).
                    if (
                        outlet.get("auto_lock_enabled")
                        and isinstance(outlet.get("lock_entity"), str)
                        and isinstance(contact, str)
                        and contact.startswith("binary_sensor.")
                    ):
                        cst = self.hass.states.get(contact)
                        lst = self.hass.states.get(outlet.get("lock_entity"))
                        contact_closed = bool(
                            cst
                            and cst.state not in ("unknown", "unavailable", "")
                            and not self._contact_sensor_state_is_open(cst.state)
                        )
                        lock_unlocked = bool(
                            lst
                            and lst.state not in ("unknown", "unavailable", "")
                            and lst.state != "locked"
                        )
                        if contact_closed and lock_unlocked:
                            delay = outlet.get("auto_lock_delay", 10)
                            # Cancel any pre-existing task first (defensive).
                            existing = self._door_auto_lock_task.pop(key, None)
                            if existing and not existing.done():
                                existing.cancel()
                            self._door_auto_lock_task[key] = self.hass.async_create_task(
                                self._run_auto_lock(outlet, room, key, delay)
                            )
                            _LOGGER.debug(
                                "Door reminder resync: re-armed auto-lock for %s (%s)",
                                outlet.get("name") or key,
                                outlet.get("lock_entity"),
                            )
                elif otype == "window":
                    key = self._door_window_key(outlet, room)
                    contact = outlet.get("contact_sensor")
                    if (
                        outlet.get("reminder_enabled")
                        and isinstance(contact, str)
                        and contact.startswith("binary_sensor.")
                    ):
                        st = self.hass.states.get(contact)
                        if (
                            st
                            and st.state not in ("unknown", "unavailable", "")
                            and self._contact_sensor_state_is_open(st.state)
                        ):
                            await self._start_door_reminder(
                                outlet,
                                room,
                                key,
                                "window_open",
                                media_player,
                                volume,
                                tts_settings,
                            )
                            _LOGGER.debug(
                                "Window reminder resync: started reminder for %s (%s)",
                                outlet.get("name") or key,
                                contact,
                            )

    def _teardown_battery_listeners(self) -> None:
        """Remove battery sensor state listeners."""
        for unsub in self._battery_listener_unsub:
            try:
                unsub()
            except Exception:
                pass
        self._battery_listener_unsub.clear()

    def _setup_battery_listeners(self) -> None:
        """Subscribe to battery sensor state changes for door/window devices."""
        self._teardown_battery_listeners()
        
        battery_sensor_ids: set[str] = set()
        
        for room in self.config_manager.energy_config.get("rooms", []):
            for outlet in room.get("outlets", []):
                otype = outlet.get("type")
                if otype in ("door", "window"):
                    # Collect all battery sensors for this device
                    for key in ("contact_sensor_battery", "lock_battery", "presence_sensor_battery"):
                        batt = outlet.get(key)
                        if batt and batt.startswith("sensor."):
                            battery_sensor_ids.add(batt)
        
        if battery_sensor_ids:
            @callback
            def _on_battery_change(event: Event) -> None:
                self.hass.async_create_task(
                    self._async_handle_battery_state_change(event)
                )
            unsub = async_track_state_change_event(
                self.hass, list(battery_sensor_ids), _on_battery_change
            )
            self._battery_listener_unsub.append(unsub)
            _LOGGER.debug("Battery listeners registered for %d sensors", len(battery_sensor_ids))

    def _find_device_by_battery_sensor(self, entity_id: str) -> tuple[dict, dict, str] | None:
        """Find the door/window outlet config, room, and battery field key for a battery sensor."""
        for room in self.config_manager.energy_config.get("rooms", []):
            for outlet in room.get("outlets", []):
                otype = outlet.get("type")
                if otype in ("door", "window"):
                    for key in ("contact_sensor_battery", "lock_battery", "presence_sensor_battery"):
                        if outlet.get(key) == entity_id:
                            return outlet, room, key
        return None

    async def _async_handle_battery_state_change(self, event: Event) -> None:
        """Handle battery sensor state change - detect low battery and battery replacement."""
        entity_id = event.data.get("entity_id")
        new_state = event.data.get("new_state")
        old_state = event.data.get("old_state")
        
        if not new_state or new_state.state in ("unknown", "unavailable"):
            return
        
        try:
            new_level = float(new_state.state)
        except (ValueError, TypeError):
            return
        
        device_info = self._find_device_by_battery_sensor(entity_id)
        if not device_info:
            return
        
        outlet, room, battery_key = device_info
        device_name = outlet.get("name") or "Device"
        room_name = room.get("name") or "Room"
        
        # Get previous level
        prev_level = self._battery_last_level.get(entity_id)
        self._battery_last_level[entity_id] = new_level
        
        tts_settings = self.config_manager.energy_config.get("tts_settings", {})
        battery_tts_enabled = tts_settings.get("battery_tts_enabled", True)
        
        if not battery_tts_enabled:
            return
        
        media_player = room.get("media_player")
        try:
            vol_raw = float(room.get("volume", 0.7) or 0.7)
        except (TypeError, ValueError):
            vol_raw = 0.7
        volume = vol_raw / 100.0 if vol_raw > 1.0 else vol_raw
        
        # Check for battery replaced (jump from low to high)
        if prev_level is not None and prev_level <= 25 and new_level >= 70:
            # Battery was just replaced
            msg_template = tts_settings.get("battery_replaced_msg") or "{device_name} battery has been successfully replaced."
            prefix = tts_settings.get("prefix", "")
            msg = _format_tts_msg(
                msg_template,
                prefix=prefix,
                device_name=device_name,
                room_name=room_name,
            )
            
            if media_player and msg:
                await self._async_send_tts_with_lights(
                    room, media_player, msg, volume, tts_settings
                )
                _LOGGER.info("Battery replaced TTS for %s: %s", device_name, msg)
            return
        
        # Check for low battery warning (at or below 25%)
        if new_level <= 25:
            now = dt_util.now()
            last_warn = self._battery_low_warn_last.get(entity_id)
            
            # Only warn once per hour
            if last_warn is None or (now - last_warn).total_seconds() >= 3600:
                msg_template = tts_settings.get("battery_low_msg") or "{device_name} battery is low at {battery_level} percent."
                prefix = tts_settings.get("prefix", "")
                msg = _format_tts_msg(
                    msg_template,
                    prefix=prefix,
                    device_name=device_name,
                    battery_level=int(new_level),
                    room_name=room_name,
                )
                
                if media_player and msg:
                    await self._async_send_tts_with_lights(
                        room, media_player, msg, volume, tts_settings
                    )
                    self._battery_low_warn_last[entity_id] = now
                    _LOGGER.info("Battery low TTS for %s (%d%%): %s", device_name, int(new_level), msg)

    def _find_door_window_outlet_by_contact_sensor(self, entity_id: str) -> tuple[dict, dict, str] | None:
        """Find the door/window outlet config and room for a contact sensor entity."""
        for room in self.config_manager.energy_config.get("rooms", []):
            for outlet in room.get("outlets", []):
                if outlet.get("type") in ("door", "window"):
                    if outlet.get("contact_sensor") == entity_id:
                        return outlet, room, outlet.get("type")
        return None

    def _find_door_outlet_by_lock(self, entity_id: str) -> tuple[dict, dict] | None:
        """Find the door outlet config and room for a lock entity."""
        for room in self.config_manager.energy_config.get("rooms", []):
            for outlet in room.get("outlets", []):
                if outlet.get("type") == "door" and outlet.get("lock_entity") == entity_id:
                    return outlet, room
        return None

    def _find_door_window_outlet_by_presence_sensor(self, entity_id: str) -> tuple[dict, dict, str] | None:
        """Find the door/window outlet config and room for a presence sensor entity."""
        for room in self.config_manager.energy_config.get("rooms", []):
            for outlet in room.get("outlets", []):
                if outlet.get("type") in ("door", "window"):
                    if outlet.get("presence_sensor") == entity_id:
                        return outlet, room, outlet.get("type")
        return None

    def _door_window_key(self, outlet: dict, room: dict) -> str:
        """Generate unique key for door/window state tracking."""
        room_id = room.get("id", room.get("name", "room").lower().replace(" ", "_"))
        outlet_name = (outlet.get("name") or "device").lower().replace(" ", "_")
        return f"{room_id}_{outlet_name}"

    def _prune_door_activity_entries(
        self, entries: list[dict[str, str]], cutoff_utc: datetime
    ) -> list[dict[str, str]]:
        """Drop door activity rows older than cutoff_utc."""
        kept: list[dict[str, str]] = []
        for entry in entries:
            ts_raw = entry.get("ts") or ""
            try:
                ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                continue
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=dt_util.UTC)
            if ts >= cutoff_utc:
                kept.append(entry)
        return kept

    def append_door_activity_event(
        self, outlet: dict, room: dict, event: str, detail: str = ""
    ) -> None:
        """Record door/window open/close/lock activity; retains last 72 hours per key.

        Previously this only logged events for ``type == "door"``, so windows
        had no activity history at all even though the UI exposes it (audit
        BUG 12). Now both door and window events are recorded.
        """
        if outlet.get("type") not in ("door", "window"):
            return
        key = self._door_window_key(outlet, room)
        now_utc = dt_util.utcnow()
        cutoff = now_utc - self._DOOR_ACTIVITY_RETENTION
        prev = self._door_activity_log.get(key) or []
        pruned = self._prune_door_activity_entries(prev, cutoff)
        pruned.append({"ts": now_utc.isoformat(), "event": event, "detail": detail})
        self._door_activity_log[key] = pruned

    def get_door_activity_events(self, outlet: dict, room: dict) -> list[dict[str, str]]:
        """Newest-first door activity rows within the retention window."""
        if outlet.get("type") != "door":
            return []
        key = self._door_window_key(outlet, room)
        now_utc = dt_util.utcnow()
        cutoff = now_utc - self._DOOR_ACTIVITY_RETENTION
        entries = self._prune_door_activity_entries(
            self._door_activity_log.get(key) or [], cutoff
        )
        self._door_activity_log[key] = entries
        return list(reversed(entries))

    def _door_lock_signal_is_baseline_or_duplicate(
        self, entity_id: str, raw: str, old_state: object | None
    ) -> bool:
        """True if contact/lock automation should be skipped (startup replay or duplicate state)."""
        last = self._door_window_last_signal_state.get(entity_id)
        if last == raw:
            return True
        old_raw: str | None = None
        if old_state is not None:
            o = getattr(old_state, "state", None)
            if o is not None and o not in ("unknown", "unavailable"):
                old_raw = str(o).strip()
        if last is None:
            if old_raw is None:
                # Absorb unknown→unknown only. Allow unknown/None→concrete so close/open
                # handlers run (avoids last staying stale and blocking real transitions).
                if raw in ("unknown", "unavailable", ""):
                    self._door_window_last_signal_state[entity_id] = raw
                    return True
                self._door_window_last_signal_state[entity_id] = raw
                return False
            if old_raw == raw:
                self._door_window_last_signal_state[entity_id] = raw
                return True
            self._door_window_last_signal_state[entity_id] = raw
            return False
        self._door_window_last_signal_state[entity_id] = raw
        return False

    async def _async_handle_contact_sensor_change(self, event: Event) -> None:
        """Handle door/window contact sensor state change."""
        entity_id = event.data.get("entity_id")
        new_state = event.data.get("new_state")
        old_state = event.data.get("old_state")
        if not entity_id:
            return
        if not new_state or new_state.state in ("unknown", "unavailable"):
            return
        if old_state and old_state.state not in ("unknown", "unavailable"):
            if new_state.state == old_state.state:
                return
        raw = str(new_state.state).strip()
        if not raw:
            return
        if self._door_lock_signal_is_baseline_or_duplicate(entity_id, raw, old_state):
            return
        
        result = self._find_door_window_outlet_by_contact_sensor(entity_id)
        if not result:
            return
        
        outlet, room, device_type = result
        key = self._door_window_key(outlet, room)
        is_open = self._contact_sensor_state_is_open(new_state.state)
        
        room_name = room.get("name", "Room")
        outlet_name = outlet.get("name", device_type.capitalize())
        media_player = room.get("media_player")
        volume = room.get("volume", 0.7)
        tts_settings = self.config_manager.energy_config.get("tts_settings", {})
        
        _LOGGER.debug(
            "%s %s state changed: %s -> %s (is_open=%s)",
            device_type.capitalize(),
            outlet_name,
            getattr(old_state, "state", None),
            new_state.state,
            is_open,
        )
        
        if device_type == "door":
            await self._handle_door_contact_change(
                outlet,
                room,
                key,
                is_open,
                media_player,
                volume,
                tts_settings,
                allow_contact_announce_tts=old_state is not None,
            )
        else:
            await self._handle_window_contact_change(
                outlet,
                room,
                key,
                is_open,
                media_player,
                volume,
                tts_settings,
                allow_contact_announce_tts=old_state is not None,
            )

    async def _handle_door_contact_change(
        self,
        outlet: dict,
        room: dict,
        key: str,
        is_open: bool,
        media_player: str | None,
        volume: float,
        tts_settings: dict,
        *,
        allow_contact_announce_tts: bool = True,
    ) -> None:
        """Handle door contact sensor state change."""
        room_name = room.get("name", "Room")
        door_type = outlet.get("door_subtype", "standard")
        door_type_text = "" if door_type == "standard" else door_type
        device_name = outlet.get("name") or "Door"

        if is_open:
            self.append_door_activity_event(outlet, room, "opened")
        else:
            self.append_door_activity_event(outlet, room, "closed")

        # Cancel any pending auto-lock if door was opened
        if is_open and key in self._door_auto_lock_task:
            task = self._door_auto_lock_task.pop(key, None)
            if task:
                task.cancel()
        
        if is_open:
            # Door opened
            if (
                allow_contact_announce_tts
                and outlet.get("announce_open_close", True)
                and media_player
            ):
                if tts_settings.get("door_tts_enabled", True) and self._tts_line_enabled(tts_settings, "door_opened"):
                    prefix = tts_settings.get("prefix", DEFAULT_TTS_PREFIX)
                    msg = tts_settings.get("door_opened_msg", DEFAULT_DOOR_OPENED_MSG)
                    message = _format_tts_msg(
                        msg,
                        prefix=prefix,
                        room_name=room_name,
                        door_type=door_type_text,
                        device_name=device_name,
                    )
                    await self._async_send_tts_with_lights(room, media_player, message, volume, tts_settings)
            
            # Turn on entities
            await self._turn_on_entities(outlet.get("open_turn_on_entities", []))
            
            # Start reminder loop if configured
            if outlet.get("reminder_mode") == "open":
                await self._start_door_reminder(outlet, room, key, "open", media_player, volume, tts_settings)
        else:
            # Door closed
            if (
                allow_contact_announce_tts
                and outlet.get("announce_open_close", True)
                and media_player
            ):
                if tts_settings.get("door_tts_enabled", True) and self._tts_line_enabled(tts_settings, "door_closed"):
                    prefix = tts_settings.get("prefix", DEFAULT_TTS_PREFIX)
                    msg = tts_settings.get("door_closed_msg", DEFAULT_DOOR_CLOSED_MSG)
                    message = _format_tts_msg(
                        msg,
                        prefix=prefix,
                        room_name=room_name,
                        door_type=door_type_text,
                        device_name=device_name,
                    )
                    await self._async_send_tts_with_lights(room, media_player, message, volume, tts_settings)
            
            # Turn off entities
            await self._turn_off_entities(outlet.get("close_turn_off_entities", []))
            
            # Stop "still open" reminder
            await self._stop_door_reminder(key)
            
            # Start auto-lock timer if enabled
            if outlet.get("auto_lock_enabled") and outlet.get("lock_entity"):
                delay = outlet.get("auto_lock_delay", 10)
                # Cancel any pre-existing pending auto-lock task for this door
                # before scheduling a new one. Previously a rapid close→open→close
                # within the delay orphaned the first task, which still fired
                # lock.lock after its original delay even though the door was
                # reopened in between (audit BUG 2).
                existing = self._door_auto_lock_task.pop(key, None)
                if existing and not existing.done():
                    existing.cancel()
                self._door_auto_lock_task[key] = self.hass.async_create_task(
                    self._run_auto_lock(outlet, room, key, delay)
                )

    async def _handle_window_contact_change(
        self,
        outlet: dict,
        room: dict,
        key: str,
        is_open: bool,
        media_player: str | None,
        volume: float,
        tts_settings: dict,
        *,
        allow_contact_announce_tts: bool = True,
    ) -> None:
        """Handle window contact sensor state change."""
        room_name = room.get("name", "Room")
        device_name = outlet.get("name") or "Window"

        # Record window activity too (audit BUG 12: previously windows had no
        # activity history).
        self.append_door_activity_event(outlet, room, "opened" if is_open else "closed")

        if is_open:
            # Window opened
            if (
                allow_contact_announce_tts
                and outlet.get("announce_open_close", True)
                and media_player
            ):
                if tts_settings.get("window_tts_enabled", True) and self._tts_line_enabled(tts_settings, "window_opened"):
                    prefix = tts_settings.get("prefix", DEFAULT_TTS_PREFIX)
                    msg = tts_settings.get("window_opened_msg", DEFAULT_WINDOW_OPENED_MSG)
                    message = _format_tts_msg(
                        msg,
                        prefix=prefix,
                        room_name=room_name,
                        device_name=device_name,
                    )
                    await self._async_send_tts_with_lights(room, media_player, message, volume, tts_settings)
            
            # Turn on entities
            await self._turn_on_entities(outlet.get("open_turn_on_entities", []))
            
            # Start reminder loop if enabled
            if outlet.get("reminder_enabled"):
                await self._start_door_reminder(outlet, room, key, "window_open", media_player, volume, tts_settings)
        else:
            # Window closed
            if (
                allow_contact_announce_tts
                and outlet.get("announce_open_close", True)
                and media_player
            ):
                if tts_settings.get("window_tts_enabled", True) and self._tts_line_enabled(tts_settings, "window_closed"):
                    prefix = tts_settings.get("prefix", DEFAULT_TTS_PREFIX)
                    msg = tts_settings.get("window_closed_msg", DEFAULT_WINDOW_CLOSED_MSG)
                    message = _format_tts_msg(
                        msg,
                        prefix=prefix,
                        room_name=room_name,
                        device_name=device_name,
                    )
                    await self._async_send_tts_with_lights(room, media_player, message, volume, tts_settings)
            
            # Turn off entities
            await self._turn_off_entities(outlet.get("close_turn_off_entities", []))
            
            # Stop reminder
            await self._stop_door_reminder(key)

    async def _async_handle_lock_state_change(self, event: Event) -> None:
        """Handle lock entity state change."""
        entity_id = event.data.get("entity_id")
        new_state = event.data.get("new_state")
        old_state = event.data.get("old_state")
        if not entity_id:
            return
        if not new_state or new_state.state in ("unknown", "unavailable"):
            return
        if old_state and old_state.state not in ("unknown", "unavailable"):
            if new_state.state == old_state.state:
                return
        raw = str(new_state.state).strip()
        if not raw:
            return
        if self._door_lock_signal_is_baseline_or_duplicate(entity_id, raw, old_state):
            return
        
        result = self._find_door_outlet_by_lock(entity_id)
        if not result:
            return
        
        outlet, room = result
        key = self._door_window_key(outlet, room)
        is_locked = new_state.state == "locked"
        allow_lock_announce_tts = old_state is not None

        room_name = room.get("name", "Room")
        door_type = outlet.get("door_subtype", "standard")
        door_type_text = "" if door_type == "standard" else door_type
        device_name = outlet.get("name") or "Door"
        media_player = room.get("media_player")
        volume = room.get("volume", 0.7)
        tts_settings = self.config_manager.energy_config.get("tts_settings", {})
        
        _LOGGER.debug(
            "Lock %s state changed: %s -> %s (is_locked=%s)",
            entity_id,
            getattr(old_state, "state", None),
            new_state.state,
            is_locked,
        )

        if is_locked:
            self.append_door_activity_event(outlet, room, "locked")
            # Door locked
            if (
                allow_lock_announce_tts
                and outlet.get("announce_lock", True)
                and media_player
            ):
                if tts_settings.get("door_tts_enabled", True) and self._tts_line_enabled(tts_settings, "door_locked"):
                    prefix = tts_settings.get("prefix", DEFAULT_TTS_PREFIX)
                    msg = tts_settings.get("door_locked_msg", DEFAULT_DOOR_LOCKED_MSG)
                    message = _format_tts_msg(
                        msg,
                        prefix=prefix,
                        room_name=room_name,
                        door_type=door_type_text,
                        device_name=device_name,
                    )
                    await self._async_send_tts_with_lights(room, media_player, message, volume, tts_settings)
            
            # Turn off entities
            await self._turn_off_entities(outlet.get("lock_turn_off_entities", []))
            
            # Stop "still unlocked" reminder
            lock_key = f"{key}_lock"
            await self._stop_door_reminder(lock_key)
            # NOTE: do NOT stop the "still open" reminder here. A smart lock can
            # report `locked` while the door is still physically open (latch
            # throws before the door closes). Stopping the open reminder here
            # suppressed a legitimate warning. Only the contact-sensor close
            # transition in _handle_door_contact_change stops that reminder
            # (audit BUG 5).
        else:
            self.append_door_activity_event(outlet, room, "unlocked")
            # Door unlocked
            if (
                allow_lock_announce_tts
                and outlet.get("announce_lock", True)
                and media_player
            ):
                if tts_settings.get("door_tts_enabled", True) and self._tts_line_enabled(tts_settings, "door_unlocked"):
                    prefix = tts_settings.get("prefix", DEFAULT_TTS_PREFIX)
                    msg = tts_settings.get("door_unlocked_msg", DEFAULT_DOOR_UNLOCKED_MSG)
                    message = _format_tts_msg(
                        msg,
                        prefix=prefix,
                        room_name=room_name,
                        door_type=door_type_text,
                        device_name=device_name,
                    )
                    await self._async_send_tts_with_lights(room, media_player, message, volume, tts_settings)
            
            # Turn on entities
            await self._turn_on_entities(outlet.get("unlock_turn_on_entities", []))
            
            # Start "still unlocked" reminder if configured
            if outlet.get("reminder_mode") == "unlocked":
                lock_key = f"{key}_lock"
                await self._start_door_reminder(outlet, room, lock_key, "unlocked", media_player, volume, tts_settings)

    async def _async_handle_door_window_presence_change(self, event: Event) -> None:
        """Handle door/window presence sensor state change."""
        entity_id = event.data.get("entity_id")
        new_state = event.data.get("new_state")
        old_state = event.data.get("old_state")

        if not new_state or new_state.state in ("unknown", "unavailable"):
            return

        # Baseline/duplicate dedupe. The contact and lock handlers gate on
        # _door_lock_signal_is_baseline_or_duplicate to avoid firing on HA
        # restart state replay; the presence handler was missing this and fired
        # spurious "Presence detected" TTS on every restart (audit BUG 3).
        if self._door_lock_signal_is_baseline_or_duplicate(
            entity_id, str(new_state.state), old_state
        ):
            return

        if old_state and old_state.state not in ("unknown", "unavailable"):
            if new_state.state == old_state.state:
                return

        result = self._find_door_window_outlet_by_presence_sensor(entity_id)
        if not result:
            return

        outlet, room, device_type = result
        key = f"{self._door_window_key(outlet, room)}_presence"
        is_detected = new_state.state == "on"  # binary_sensor: on = detected

        room_name = room.get("name", "Room")
        device_name = outlet.get("name") or ("Door" if device_type == "door" else "Window")
        media_player = room.get("media_player")
        volume = room.get("volume", 0.7)
        tts_settings = self.config_manager.energy_config.get("tts_settings", {})

        _LOGGER.debug(
            "%s presence sensor %s: %s -> %s (detected=%s)",
            device_type.capitalize(),
            entity_id,
            getattr(old_state, "state", None),
            new_state.state,
            is_detected,
        )

        if is_detected:
            # Presence detected
            hold_secs = outlet.get("presence_on_hold_secs", 0)
            if hold_secs > 0:
                # Track this task so it can be cancelled on teardown or on a
                # new event for the same key. Previously the fire-and-forget
                # task was uncancellable and survived HA shutdown (audit BUG 4).
                existing = self._presence_handler_tasks.pop(key, None)
                if existing and not existing.done():
                    existing.cancel()
                task = self.hass.async_create_task(
                    self._async_presence_hold_then_announce(
                        entity_id, outlet, room, key, room_name, device_name,
                        media_player, volume, tts_settings, hold_secs,
                        on_clear=False,
                    )
                )
                self._presence_handler_tasks[key] = task
                return

            if outlet.get("announce_presence") and media_player:
                if tts_settings.get("presence_tts_enabled", True) and self._tts_line_enabled(tts_settings, "presence_detected"):
                    prefix = tts_settings.get("prefix", DEFAULT_TTS_PREFIX)
                    msg = tts_settings.get("presence_detected_msg", DEFAULT_PRESENCE_DETECTED_MSG)
                    message = _format_tts_msg(
                        msg,
                        prefix=prefix,
                        room_name=room_name,
                        device_name=device_name,
                    )
                    await self._async_send_tts_with_lights(room, media_player, message, volume, tts_settings)

            await self._turn_on_entities(outlet.get("presence_on_entities", []))
        else:
            # Presence cleared
            hold_secs = outlet.get("presence_off_hold_secs", 0)
            if hold_secs > 0:
                existing = self._presence_handler_tasks.pop(key, None)
                if existing and not existing.done():
                    existing.cancel()
                task = self.hass.async_create_task(
                    self._async_presence_hold_then_announce(
                        entity_id, outlet, room, key, room_name, device_name,
                        media_player, volume, tts_settings, hold_secs,
                        on_clear=True,
                    )
                )
                self._presence_handler_tasks[key] = task
                return

            if outlet.get("announce_presence") and media_player:
                if tts_settings.get("presence_tts_enabled", True) and self._tts_line_enabled(tts_settings, "presence_cleared"):
                    prefix = tts_settings.get("prefix", DEFAULT_TTS_PREFIX)
                    msg = tts_settings.get("presence_cleared_msg", DEFAULT_PRESENCE_CLEARED_MSG)
                    message = _format_tts_msg(
                        msg,
                        prefix=prefix,
                        room_name=room_name,
                        device_name=device_name,
                    )
                    await self._async_send_tts_with_lights(room, media_player, message, volume, tts_settings)

            await self._turn_off_entities(outlet.get("presence_off_entities", []))

    async def _async_presence_hold_then_announce(
        self,
        entity_id: str,
        outlet: dict,
        room: dict,
        key: str,
        room_name: str,
        device_name: str,
        media_player: str | None,
        volume: float,
        tts_settings: dict,
        hold_secs: float,
        *,
        on_clear: bool,
    ) -> None:
        """Wait ``hold_secs`` then announce presence change if still in that state.

        Extracted from ``_async_handle_door_window_presence_change`` so the
        hold sleep is cancellable (audit BUG 4). Checks ``self._running`` after
        the sleep so a teardown during the hold does not fire TTS.
        """
        try:
            await asyncio.sleep(hold_secs)
            if not self._running:
                return
            expected_state = "off" if on_clear else "on"
            current = self.hass.states.get(entity_id)
            if not current or current.state != expected_state:
                return
            msg_key = "presence_cleared" if on_clear else "presence_detected"
            default_tmpl = (
                DEFAULT_PRESENCE_CLEARED_MSG if on_clear else DEFAULT_PRESENCE_DETECTED_MSG
            )
            if outlet.get("announce_presence") and media_player:
                if tts_settings.get("presence_tts_enabled", True) and self._tts_line_enabled(
                    tts_settings, msg_key
                ):
                    prefix = tts_settings.get("prefix", DEFAULT_TTS_PREFIX)
                    msg = tts_settings.get(f"{msg_key}_msg", default_tmpl)
                    message = _format_tts_msg(
                        msg,
                        prefix=prefix,
                        room_name=room_name,
                        device_name=device_name,
                    )
                    await self._async_send_tts_with_lights(
                        room, media_player, message, volume, tts_settings
                    )
            entities_key = "presence_off_entities" if on_clear else "presence_on_entities"
            turn = self._turn_off_entities if on_clear else self._turn_on_entities
            await turn(outlet.get(entities_key, []))
        except asyncio.CancelledError:
            # Superseded by a newer event for the same key, or monitor teardown.
            raise
        except Exception as e:
            _LOGGER.warning("Presence hold-then-announce failed for %s: %s", entity_id, e)
        finally:
            # Only clear our slot if it still points at us.
            current_task = self._presence_handler_tasks.get(key)
            if current_task is None or current_task is asyncio.current_task():
                self._presence_handler_tasks.pop(key, None)

    async def _async_door_reminder_power_enforcement_hook(
        self,
        room: dict,
        media_player: str | None,
        volume: float,
        tts_settings: dict,
        *,
        reminder_kind: str,
    ) -> None:
        """Log door/window still-open or still-unlocked reminders without counting as a room warning.

        Door/window reminders are informational TTS — they should appear in the
        event log but must NOT increment the room warning count, record a
        threshold warning, or push the room toward power enforcement phases.
        """
        if not media_player:
            return
        if not _normalize_presence_person_entity(room.get("presence_person_entity")):
            return
        room_id = room.get("id", str(room.get("name") or "room").lower().replace(" ", "_"))
        if not self.config_manager.is_room_enforcement_enabled(room_id):
            return

        current_watts = self._sum_room_total_watts_only(room)
        room_name = room.get("name", "Room")
        volume_pct = int(round(float(volume) * 100))

        try:
            rt_raw = room.get("threshold", 0)
            try:
                rt_int = int(rt_raw) if rt_raw is not None else 0
            except (TypeError, ValueError):
                rt_int = 0

            log_extra: dict = {
                "room_watts": int(round(current_watts)),
                "room_threshold": rt_int,
                "volume_percent": volume_pct,
                "door_reminder": reminder_kind,
                "counted_as_warning": False,
            }
            try:
                log_extra["enforcement_phase"] = int(
                    self.config_manager.get_enforcement_state(room_id).get("phase", 0) or 0
                )
            except Exception:
                pass

            await self.config_manager.async_add_event_log_entry(
                room_id,
                room_name,
                "warning",
                None,
                True,
                extra=log_extra,
            )
        except Exception as e:
            _LOGGER.error("Door reminder event log failed: %s", e)

    async def _start_door_reminder(
        self, outlet: dict, room: dict, key: str, reminder_type: str,
        media_player: str | None, volume: float, tts_settings: dict
    ) -> None:
        """Start a reminder loop for open door/window or unlocked door."""
        # Stop any existing reminder for this key
        await self._stop_door_reminder(key)
        
        interval = outlet.get("reminder_interval", 30)
        room_name = room.get("name", "Room")
        door_type = outlet.get("door_subtype", "standard")
        door_type_text = "" if door_type == "standard" else door_type
        
        async def reminder_loop():
            while self._running:
                await asyncio.sleep(interval)
                
                # Check if condition still applies
                if reminder_type == "open":
                    contact = outlet.get("contact_sensor")
                    state = self.hass.states.get(contact)
                    if not state or not self._contact_sensor_state_is_open(state.state):
                        break
                    lock_ent = str(outlet.get("lock_entity") or "").strip()
                    if lock_ent.startswith("lock."):
                        lstate = self.hass.states.get(lock_ent)
                        if lstate and lstate.state == "locked":
                            break
                    msg_key = "door_still_open"
                    msg_template = tts_settings.get("door_still_open_msg", DEFAULT_DOOR_STILL_OPEN_MSG)
                elif reminder_type == "window_open":
                    contact = outlet.get("contact_sensor")
                    state = self.hass.states.get(contact)
                    if not state or not self._contact_sensor_state_is_open(state.state):
                        break
                    msg_key = "window_still_open"
                    msg_template = tts_settings.get("window_still_open_msg", DEFAULT_WINDOW_STILL_OPEN_MSG)
                elif reminder_type == "unlocked":
                    lock = outlet.get("lock_entity")
                    state = self.hass.states.get(lock)
                    if not state or state.state == "locked":
                        break
                    msg_key = "door_still_unlocked"
                    msg_template = tts_settings.get("door_still_unlocked_msg", DEFAULT_DOOR_STILL_UNLOCKED_MSG)
                else:
                    break
                
                # Send TTS reminder
                if media_player and self._tts_line_enabled(tts_settings, msg_key):
                    tts_enabled_key = (
                        "door_tts_enabled"
                        if reminder_type in ("open", "unlocked")
                        else "window_tts_enabled"
                    )
                    if tts_settings.get(tts_enabled_key, True):
                        prefix = tts_settings.get("prefix", DEFAULT_TTS_PREFIX)
                        device_name = outlet.get("name") or (
                            "Door" if reminder_type in ("open", "unlocked") else "Window"
                        )
                        message = _format_tts_msg(
                            msg_template,
                            prefix=prefix,
                            room_name=room_name,
                            door_type=door_type_text,
                            device_name=device_name,
                        )
                        await self._async_send_tts_with_lights(room, media_player, message, volume, tts_settings)
                        await self._async_door_reminder_power_enforcement_hook(
                            room,
                            media_player,
                            volume,
                            tts_settings,
                            reminder_kind=msg_key,
                        )

        self._door_reminder_active[key] = self.hass.async_create_task(reminder_loop())

    async def _stop_door_reminder(self, key: str) -> None:
        """Stop reminder loop for a given key."""
        task = self._door_reminder_active.pop(key, None)
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def _run_auto_lock(self, outlet: dict, room: dict, key: str, delay: int) -> None:
        """Wait delay then lock the door if still closed."""
        try:
            await asyncio.sleep(delay)
            
            # Check if door is still closed
            contact = outlet.get("contact_sensor")
            state = self.hass.states.get(contact)
            if not state or self._contact_sensor_state_is_open(state.state):
                return
            
            lock_entity = outlet.get("lock_entity")
            if lock_entity:
                _LOGGER.info("Auto-locking door: %s after %ds", lock_entity, delay)
                await self.hass.services.async_call(
                    "lock", "lock",
                    {"entity_id": lock_entity},
                    blocking=True
                )
        except asyncio.CancelledError:
            pass
        except Exception as e:
            _LOGGER.error("Auto-lock failed: %s", e)
        finally:
            self._door_auto_lock_task.pop(key, None)

    async def _turn_on_entities(self, entities: list[str]) -> None:
        """Turn on a list of light/switch entities."""
        for entity_id in entities:
            if not entity_id:
                continue
            domain = entity_id.split(".", 1)[0] if "." in entity_id else None
            if domain in ("light", "switch"):
                try:
                    await self.hass.services.async_call(
                        domain, "turn_on",
                        {"entity_id": entity_id},
                        blocking=False
                    )
                except Exception as e:
                    _LOGGER.error("Failed to turn on %s: %s", entity_id, e)

    async def _turn_off_entities(self, entities: list[str]) -> None:
        """Turn off a list of light/switch entities."""
        for entity_id in entities:
            if not entity_id:
                continue
            domain = entity_id.split(".", 1)[0] if "." in entity_id else None
            if domain in ("light", "switch"):
                try:
                    await self.hass.services.async_call(
                        domain, "turn_off",
                        {"entity_id": entity_id},
                        blocking=False
                    )
                except Exception as e:
                    _LOGGER.error("Failed to turn off %s: %s", entity_id, e)


async def async_start_energy_monitor(
    hass: HomeAssistant, config_manager: "ConfigManager"
) -> None:
    """Start the energy monitor."""
    monitor = EnergyMonitor(hass, config_manager)
    await monitor.async_start()
    hass.data[DOMAIN]["energy_monitor"] = monitor
    hass.data[DOMAIN]["energy_monitor_task"] = monitor._task
