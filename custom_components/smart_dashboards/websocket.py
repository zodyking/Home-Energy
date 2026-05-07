"""WebSocket API for Smart Dashboards."""
from __future__ import annotations

import asyncio
import logging
from copy import deepcopy
import time
from datetime import date, datetime, timedelta
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import Context, HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from .config_manager import (
    _normalize_room_budget_boost_weekdays,
    outdoor_temperature_from_entity,
    resolve_wall_heater_effective_temperatures,
    vent_like_energy_tracking_key,
)
from .const import DEFAULT_NOTIFICATION_TITLE, DOMAIN
from .efficiency_digest import (
    async_reschedule_efficiency_digest,
    async_send_efficiency_digest_test,
)
from .mobile_notify_target import async_send_notify_push
from .room_ratings import (
    compute_intraday_ratings,
    compute_monthly_ratings,
    efficiency_scoring_params_from_manager,
    load_ratings,
    ratings_payload_for_ws,
    ratings_store_path,
    record_dashboard_heartbeat,
    recompute_room_ratings,
    save_ratings,
)
from .statistics_aggregation import (
    MODE_ENERGY_CHANGE,
    MODE_POWER_INTEGRATION,
    entity_statistics_mode,
    sync_sum_energy_change_wh,
)

_LOGGER = logging.getLogger(__name__)


def _dashboard_ws_user_key(connection: websocket_api.ActiveConnection) -> str:
    """Stable key for engagement heartbeats (per HA user)."""
    user = connection.user
    if user is None:
        return "anonymous"
    return str(user.id)


def _ws_connection_user_is_admin(connection: websocket_api.ActiveConnection) -> bool:
    """True if the websocket user is active and in the admin group (or owner)."""
    user = connection.user
    if user is None or not user.is_active:
        return False
    return bool(user.is_admin)


def _assignee_matches_connection_user(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    person_ent: str,
) -> bool:
    """True if the logged-in user is the person linked to the room (or admin)."""
    if _ws_connection_user_is_admin(connection):
        return True
    user = connection.user
    if not user or not person_ent:
        return False
    pe = str(person_ent).strip()
    st = hass.states.get(pe) or hass.states.get(pe.lower())
    if not st:
        return False
    uid = st.attributes.get("user_id")
    if uid is not None and str(uid).strip() == str(user.id):
        return True
    un = (user.name or "").lower().strip()
    pn = (st.attributes.get("friendly_name") or "").lower().strip()
    return bool(pn) and un == pn


def _room_budget_boost_assignee_only(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    person_ent: str,
) -> bool:
    """True if websocket user is the room's assigned person. Admins are not exempt."""
    user = connection.user
    if not user or not person_ent:
        return False
    pe = str(person_ent).strip()
    st = hass.states.get(pe) or hass.states.get(pe.lower())
    if not st:
        return False
    uid = st.attributes.get("user_id")
    if uid is not None and str(uid).strip() == str(user.id):
        return True
    un = (user.name or "").lower().strip()
    pn = (st.attributes.get("friendly_name") or "").lower().strip()
    return bool(pn) and un == pn


def _attach_stove_timer_to_outlet_data(
    outlet_data: dict[str, Any],
    outlet: dict[str, Any],
    energy_monitor: Any,
) -> None:
    """Add timer_phase and time_remaining for stove outlets (matches get_stove_data logic)."""
    if outlet.get("type") != "stove" or not outlet.get("plug1_entity"):
        return
    key = outlet["plug1_entity"]
    cooking_time_minutes = int(outlet.get("cooking_time_minutes", 15))
    final_warning_seconds = int(outlet.get("final_warning_seconds", 30))
    cooking_time_sec = max(1, cooking_time_minutes) * 60
    final_warning_sec = max(1, min(final_warning_seconds, 300))
    outlet_data["timer_phase"] = "none"
    outlet_data["time_remaining"] = 0
    if not energy_monitor or not hasattr(energy_monitor, "_stove_timer_phase"):
        return
    outlet_data["timer_phase"] = energy_monitor._stove_timer_phase.get(key, "none")
    timer_start = (
        energy_monitor._stove_timer_start.get(key)
        if isinstance(getattr(energy_monitor, "_stove_timer_start", None), dict)
        else None
    )
    timer_phase = outlet_data["timer_phase"]
    if timer_start and timer_phase != "none":
        now = dt_util.now()
        elapsed = (now - timer_start).total_seconds()
        if timer_phase == "15min":
            outlet_data["time_remaining"] = int(max(0, cooking_time_sec - elapsed))
        elif timer_phase == "30sec":
            outlet_data["time_remaining"] = int(max(0, final_warning_sec - elapsed))


def _parse_temperature_sensor_state(hass: HomeAssistant, entity_id: str | None) -> float | None:
    st = hass.states.get(entity_id or "")
    if not st or st.state in ("unknown", "unavailable", ""):
        return None
    try:
        return float(st.state)
    except (TypeError, ValueError):
        return None


def _attach_wall_heater_dashboard_fields(
    outlet_data: dict[str, Any],
    outlet: dict[str, Any],
    room_id: str,
    hass: HomeAssistant,
    energy_monitor: Any,
) -> None:
    """Expose live temp, thresholds, and run timer for wall heater cards."""
    if outlet.get("type") != "wall_heater":
        return
    weather_ent = str(outlet.get("heater_weather_entity") or "").strip()
    outdoor = (
        outdoor_temperature_from_entity(hass, weather_ent) if weather_ent else None
    )
    eff_on, eff_comfort, boost_active = resolve_wall_heater_effective_temperatures(
        outlet, outdoor
    )
    outlet_data["heater_on_below_temperature"] = round(eff_on, 2)
    outlet_data["heater_comfort_temperature"] = round(eff_comfort, 2)
    outlet_data["heater_effective_on_below"] = round(eff_on, 2)
    outlet_data["heater_effective_comfort"] = round(eff_comfort, 2)
    outlet_data["heater_cold_boost_active"] = boost_active
    te = str(outlet.get("heater_temperature_entity") or "").strip()
    outlet_data["heater_current_temperature"] = (
        _parse_temperature_sensor_state(hass, te) if te.startswith("sensor.") else None
    )
    outlet_data["heater_time_remaining_sec"] = 0
    outlet_data["heater_weather_entity"] = outlet.get("heater_weather_entity", "")
    outlet_data["heater_optimization_enabled"] = outlet.get("heater_optimization_enabled", True)
    outlet_data["heater_hysteresis_band"] = outlet.get("heater_hysteresis_band", 2.0)
    outlet_data["heater_duty_cycle_enabled"] = outlet.get("heater_duty_cycle_enabled", False)
    outlet_data["heater_duty_on_minutes"] = outlet.get("heater_duty_on_minutes", 5)
    outlet_data["heater_duty_off_minutes"] = outlet.get("heater_duty_off_minutes", 2)
    outlet_data["heater_duty_comfort_margin"] = outlet.get("heater_duty_comfort_margin", 1.0)
    outlet_data["heater_power_aware_enabled"] = outlet.get("heater_power_aware_enabled", False)
    outlet_data["heater_power_threshold_watts"] = outlet.get("heater_power_threshold_watts", 500)
    outlet_data["heater_learning_enabled"] = outlet.get("heater_learning_enabled", True)
    outlet_data["heater_preheat_minutes"] = outlet.get("heater_preheat_minutes", 30)
    outlet_data["heater_door_sensor_entity"] = outlet.get("heater_door_sensor_entity")
    outlet_data["heater_window_sensor_entity"] = outlet.get("heater_window_sensor_entity")
    slug = (outlet.get("name") or "device").lower().replace(" ", "_")
    key = f"{room_id}|{slug}"
    if energy_monitor and hasattr(energy_monitor, "_heater_automation_state"):
        st = energy_monitor._heater_automation_state.get(key) or {}
        ru = st.get("run_until")
        if ru is not None:
            now = dt_util.now()
            try:
                sec = (ru - now).total_seconds()
                outlet_data["heater_time_remaining_sec"] = int(max(0, sec))
            except TypeError:
                pass
    if energy_monitor and hasattr(energy_monitor, "_heater_smart_state"):
        smart_st = energy_monitor._heater_smart_state.get(key) or {}
        outlet_data["heater_smart_mode"] = smart_st.get("smart_mode", "idle")
        outlet_data["heater_heating_rate"] = round(smart_st.get("heating_rate", 0.0), 3)
        outlet_data["heater_cooling_rate"] = round(smart_st.get("cooling_rate", 0.0), 3)


# Server-side cache for get_statistics to avoid heavy recorder queries
# Short TTL while range includes "today" (live); longer TTL for past-only ranges
_STATISTICS_CACHE: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}
_STATISTICS_CACHE_TTL_LIVE = 60.0
_STATISTICS_CACHE_TTL_PAST = 3600.0
_STATISTICS_QUERY_CONCURRENCY = 6
# Shared result of _compute_kwh_from_history — same work as get_statistics + billing daily chart
# (cleared with statistics cache when energy config changes; TTL is range-dependent)
_KWH_HISTORY_CACHE: dict[
    tuple[str, str],
    tuple[float, tuple[float, dict[str, float], dict[str, dict[str, float]]]],
] = {}
# Throttle background cache priming vs. statistics_refresh_seconds
_last_stats_prime_at: float = 0.0


async def async_register_statistics_cache_primer(hass: HomeAssistant) -> None:
    """Periodic background prime of default-range statistics cache and save to JSON."""
    _clear_recorder_derived_caches()

    async def _tick(_now: datetime) -> None:
        await _statistics_cache_prime_tick(hass, _now)

    async_track_time_interval(hass, _tick, timedelta(seconds=15))


@callback
def async_setup(hass: HomeAssistant) -> None:
    """Set up WebSocket API."""
    websocket_api.async_register_command(hass, websocket_get_config)
    websocket_api.async_register_command(hass, websocket_save_energy)
    websocket_api.async_register_command(hass, websocket_get_entities)
    websocket_api.async_register_command(hass, websocket_send_tts)
    websocket_api.async_register_command(hass, websocket_set_volume)
    websocket_api.async_register_command(hass, websocket_get_power_data)
    websocket_api.async_register_command(hass, websocket_get_daily_history)
    websocket_api.async_register_command(hass, websocket_get_intraday_history)
    websocket_api.async_register_command(hass, websocket_get_intraday_events)
    websocket_api.async_register_command(hass, websocket_get_event_log)
    websocket_api.async_register_command(hass, websocket_get_statistics)
    websocket_api.async_register_command(hass, websocket_subscribe_statistics)
    websocket_api.async_register_command(hass, websocket_subscribe_hard_refresh_progress)
    websocket_api.async_register_command(hass, websocket_get_entities_by_area)
    websocket_api.async_register_command(hass, websocket_get_areas)
    websocket_api.async_register_command(hass, websocket_get_switches)
    websocket_api.async_register_command(hass, websocket_verify_passcode)
    websocket_api.async_register_command(hass, websocket_check_toggle_auth)
    websocket_api.async_register_command(hass, websocket_set_room_budget_boost_days)
    websocket_api.async_register_command(hass, websocket_toggle_switch)
    websocket_api.async_register_command(hass, websocket_get_breaker_data)
    websocket_api.async_register_command(hass, websocket_test_trip_breaker)
    websocket_api.async_register_command(hass, websocket_get_stove_data)
    websocket_api.async_register_command(hass, websocket_send_test_notification)
    websocket_api.async_register_command(hass, websocket_clear_statistics_cache)
    websocket_api.async_register_command(hass, websocket_hard_refresh_statistics)
    websocket_api.async_register_command(hass, websocket_get_statistics_sources)
    websocket_api.async_register_command(hass, websocket_get_statistics_source_breakdown)
    websocket_api.async_register_command(hass, websocket_get_zone_health_status)
    websocket_api.async_register_command(hass, websocket_refresh_zone_health)
    websocket_api.async_register_command(hass, websocket_get_room_ratings)
    websocket_api.async_register_command(hass, websocket_dashboard_heartbeat)
    websocket_api.async_register_command(hass, websocket_send_efficiency_digest_test)
    websocket_api.async_register_command(hass, websocket_get_light_automations)
    websocket_api.async_register_command(hass, websocket_save_light_automations)
    websocket_api.async_register_command(hass, websocket_test_tuya_scene)
    _LOGGER.info("Smart Dashboards WebSocket API registered")


@websocket_api.websocket_command(
    {
        vol.Required("type"): "smart_dashboards/get_config",
    }
)
@websocket_api.async_response
async def websocket_get_config(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Get the full configuration."""
    config_manager = hass.data[DOMAIN].get("config_manager")
    if config_manager:
        connection.send_result(msg["id"], config_manager.config)
    else:
        connection.send_error(msg["id"], "not_ready", "Config manager not initialized")


@websocket_api.websocket_command(
    {
        vol.Required("type"): "smart_dashboards/save_energy",
        vol.Required("config"): dict,
    }
)
@websocket_api.async_response
async def websocket_save_energy(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Save energy configuration."""
    config_manager = hass.data[DOMAIN].get("config_manager")
    if not config_manager:
        connection.send_error(msg["id"], "not_ready", "Config manager not initialized")
        return
    try:
        await config_manager.async_update_energy(msg["config"])
        _reset_statistics_prime_clock()
        _clear_recorder_derived_caches()
        connection.send_result(msg["id"], {"success": True})
        hass.async_create_task(_prime_statistics_cache(hass))
        hass.async_create_task(async_reschedule_efficiency_digest(hass))
    except Exception as e:
        _LOGGER.exception("Failed to save energy config: %s", e)
        connection.send_error(msg["id"], "save_failed", str(e))


@websocket_api.websocket_command(
    {
        vol.Required("type"): "smart_dashboards/get_entities",
        vol.Optional("entity_type"): str,
    }
)
@websocket_api.async_response
async def websocket_get_entities(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Get available entities (media players, power sensors, etc.)."""
    entity_type = msg.get("entity_type")
    result: dict[str, list[dict[str, str]]] = {
        "media_players": [],
        "power_sensors": [],
        "sensors": [],
        "binary_sensors": [],
        "lights": [],
        "input_text": [],
        "input_number": [],
        "persons": [],
        "zones": [],
        "weather": [],
    }

    for state in hass.states.async_all():
        entity_id = state.entity_id
        friendly_name = state.attributes.get("friendly_name", entity_id)

        if entity_type is None or entity_type == "media_player":
            if entity_id.startswith("media_player."):
                result["media_players"].append({
                    "entity_id": entity_id,
                    "friendly_name": friendly_name,
                })

        if entity_type is None or entity_type == "sensor":
            if entity_id.startswith("sensor."):
                result["sensors"].append({
                    "entity_id": entity_id,
                    "friendly_name": friendly_name,
                    "unit": state.attributes.get("unit_of_measurement", ""),
                })

        if entity_type is None or entity_type == "power_sensor":
            # Include sensors with power in name or unit
            if entity_id.startswith("sensor."):
                unit = state.attributes.get("unit_of_measurement", "")
                if "power" in entity_id.lower() or unit in ("W", "kW", "mW"):
                    result["power_sensors"].append({
                        "entity_id": entity_id,
                        "friendly_name": friendly_name,
                        "unit": unit,
                    })
            # Include switches with power attribute
            elif entity_id.startswith("switch."):
                if "current_power_w" in state.attributes:
                    result["power_sensors"].append({
                        "entity_id": entity_id,
                        "friendly_name": friendly_name,
                        "unit": "W",
                        "type": "switch_attribute",
                    })

        if entity_type is None or entity_type == "binary_sensor":
            if entity_id.startswith("binary_sensor."):
                result["binary_sensors"].append({
                    "entity_id": entity_id,
                    "friendly_name": friendly_name,
                })

        if entity_type is None or entity_type == "light":
            if entity_id.startswith("light."):
                result["lights"].append({
                    "entity_id": entity_id,
                    "friendly_name": friendly_name,
                })

        if entity_type is None or entity_type == "input_text":
            if entity_id.startswith("input_text."):
                result["input_text"].append({
                    "entity_id": entity_id,
                    "friendly_name": friendly_name,
                })

        if entity_type is None or entity_type == "input_number":
            if entity_id.startswith("input_number."):
                result["input_number"].append({
                    "entity_id": entity_id,
                    "friendly_name": friendly_name,
                })

        if entity_type is None or entity_type == "person":
            if entity_id.startswith("person."):
                dts = state.attributes.get("device_trackers") or []
                if isinstance(dts, list) and any(
                    isinstance(dt, str) and dt.startswith("device_tracker.") for dt in dts
                ):
                    result["persons"].append({
                        "entity_id": entity_id,
                        "friendly_name": friendly_name,
                    })

        if entity_type is None or entity_type == "zone":
            if entity_id.startswith("zone."):
                result["zones"].append({
                    "entity_id": entity_id,
                    "friendly_name": friendly_name,
                })

        if entity_type is None or entity_type == "weather":
            if entity_id.startswith("weather."):
                result["weather"].append({
                    "entity_id": entity_id,
                    "friendly_name": friendly_name,
                })

    connection.send_result(msg["id"], result)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "smart_dashboards/send_tts",
        vol.Required("media_player"): str,
        vol.Required("message"): str,
        vol.Optional("language"): str,
        vol.Optional("volume"): vol.Coerce(float),
    }
)
@websocket_api.async_response
async def websocket_send_tts(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Send TTS to a media player (waits for on/idle/standby if not ready)."""
    from .tts_queue import async_send_tts_or_queue

    try:
        await async_send_tts_or_queue(
            hass,
            media_player=msg["media_player"],
            message=msg["message"],
            language=msg.get("language"),
            volume=msg.get("volume"),
        )
        connection.send_result(msg["id"], {"success": True})
    except Exception as e:
        _LOGGER.error("TTS failed: %s", e)
        connection.send_error(msg["id"], "tts_failed", str(e))


@websocket_api.websocket_command(
    {
        vol.Required("type"): "smart_dashboards/set_volume",
        vol.Required("media_player"): str,
        vol.Required("volume"): vol.Coerce(float),
    }
)
@websocket_api.async_response
async def websocket_set_volume(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Set volume on a media player."""
    from .tts_helper import async_set_volume

    try:
        await async_set_volume(
            hass,
            media_player=msg["media_player"],
            volume=msg["volume"],
        )
        connection.send_result(msg["id"], {"success": True})
    except Exception as e:
        _LOGGER.error("Set volume failed: %s", e)
        connection.send_error(msg["id"], "volume_failed", str(e))


def build_rooms_payload_for_power_and_ratings(
    hass: HomeAssistant,
    config_manager: Any,
) -> list[dict[str, Any]]:
    """Room rows (ids, day Wh, event counts, outlets) for get_power_data and intraday ratings."""
    event_counts = config_manager.get_event_counts()
    energy_monitor = hass.data.get(DOMAIN, {}).get("energy_monitor")
    rooms_out: list[dict[str, Any]] = []

    for room in config_manager.energy_config.get("rooms", []):
        room_id = room.get("id", room["name"].lower().replace(" ", "_"))
        room_data = {
            "id": room_id,
            "name": room["name"],
            "total_watts": 0,
            "total_day_wh": 0,
            "warnings": event_counts.get("room_warnings", {}).get(room_id, 0),
            "shutoffs": event_counts.get("room_shutoffs", {}).get(room_id, 0),
            "power_cycles": event_counts.get("room_power_cycles", {}).get(room_id, 0),
            "outlets": [],
        }

        for outlet in room.get("outlets", []):
            outlet_type = outlet.get("type", "outlet")
            outlet_data = {
                "name": outlet["name"],
                "type": outlet_type,
                "plug1": {"watts": 0, "day_wh": 0},
                "plug2": {"watts": 0, "day_wh": 0},
            }

            if outlet_type == "light":
                # Cumulative Wh is independent of switch state (same as plugs); watts only when on.
                switch_entity = outlet.get("switch_entity")
                if switch_entity:
                    state = hass.states.get(switch_entity)
                    is_on = bool(state and (state.state or "off").lower() in ("on",))
                    outlet_data["switch_state"] = is_on
                    power_ent = (
                        outlet.get("power_sensor_entity")
                        if outlet.get("power_source") == "sensor"
                        else None
                    )
                    if power_ent:
                        total_day_wh = config_manager.get_day_energy(power_ent)
                        total_watts = (
                            _get_power_value(hass, power_ent) if is_on else 0.0
                        )
                    else:
                        light_ents = outlet.get("light_entities") or []
                        tracking_key = f"light_{room_id}_{(outlet.get('name') or 'light').lower().replace(' ', '_')}"
                        configured_w = 0.0
                        for le in light_ents:
                            if isinstance(le, dict) and le.get("entity_id", "").startswith(
                                "light."
                            ):
                                configured_w += float(le.get("watts", 0) or 0)
                        total_watts = configured_w if is_on else 0.0
                        total_day_wh = config_manager.get_day_energy(tracking_key)
                    outlet_data["plug1"] = {
                        "watts": total_watts,
                        "day_wh": round(total_day_wh, 2),
                    }
                    room_data["total_watts"] += total_watts
                    room_data["total_day_wh"] += total_day_wh
                else:
                    outlet_data["switch_state"] = False
            elif outlet_type in ("vent", "wall_heater"):
                # Vent / wall heater: power sensor reads directly (like AC), or static watts when switch on
                switch_entity = outlet.get("switch_entity")
                watts_when_on = float(outlet.get("watts_when_on", 0) or 0)
                power_ent = (
                    outlet.get("power_sensor_entity")
                    if outlet.get("power_source") == "sensor"
                    else None
                )
                if power_ent:
                    # Power sensor mode: read sensor directly (sensor reports 0W when off)
                    watts = _get_power_value(hass, power_ent)
                    day_wh = config_manager.get_day_energy(power_ent)
                elif switch_entity:
                    # Fixed watts mode: use watts_when_on only when switch is on
                    state = hass.states.get(switch_entity)
                    is_on = bool(state and (state.state or "off").lower() in ("on",))
                    watts = watts_when_on if is_on else 0.0
                    tracking_key = vent_like_energy_tracking_key(room_id, outlet)
                    day_wh = config_manager.get_day_energy(tracking_key)
                else:
                    watts = 0.0
                    tracking_key = vent_like_energy_tracking_key(room_id, outlet)
                    day_wh = config_manager.get_day_energy(tracking_key)
                outlet_data["plug1"] = {"watts": watts, "day_wh": round(day_wh, 2)}
                room_data["total_watts"] += watts
                room_data["total_day_wh"] += day_wh
            else:
                # Get plug 1 data
                if outlet.get("plug1_entity"):
                    watts = _get_power_value(hass, outlet["plug1_entity"])
                    day_wh = config_manager.get_day_energy(outlet["plug1_entity"])
                    outlet_data["plug1"] = {"watts": watts, "day_wh": round(day_wh, 2)}
                    room_data["total_watts"] += watts
                    room_data["total_day_wh"] += day_wh

                # Get plug 2 data
                if outlet.get("plug2_entity"):
                    watts = _get_power_value(hass, outlet["plug2_entity"])
                    day_wh = config_manager.get_day_energy(outlet["plug2_entity"])
                    outlet_data["plug2"] = {"watts": watts, "day_wh": round(day_wh, 2)}
                    room_data["total_watts"] += watts
                    room_data["total_day_wh"] += day_wh

            _attach_stove_timer_to_outlet_data(outlet_data, outlet, energy_monitor)
            _attach_wall_heater_dashboard_fields(
                outlet_data, outlet, room_id, hass, energy_monitor
            )
            room_data["outlets"].append(outlet_data)

        room_data["total_watts"] = round(room_data["total_watts"], 1)
        room_data["total_day_wh"] = round(room_data["total_day_wh"], 2)
        base_k, eff_k = config_manager.get_room_kwh_budgets(room_id)
        room_data["kwh_budget"] = round(base_k, 4)
        room_data["kwh_budget_effective"] = round(eff_k, 4)
        if config_manager.is_room_enforcement_enabled(room_id):
            phase = int(
                config_manager.get_enforcement_state(room_id).get("phase", 0) or 0
            )
            room_data["enforcement_phase"] = max(0, min(2, phase))
        rooms_out.append(room_data)

    return rooms_out


@websocket_api.websocket_command(
    {
        vol.Required("type"): "smart_dashboards/get_power_data",
    }
)
@websocket_api.async_response
async def websocket_get_power_data(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Get current power readings for all configured outlets."""
    config_manager = hass.data[DOMAIN].get("config_manager")
    if not config_manager:
        connection.send_error(msg["id"], "not_ready", "Config manager not initialized")
        return

    event_counts = config_manager.get_event_counts()
    result: dict[str, Any] = {
        "rooms": build_rooms_payload_for_power_and_ratings(hass, config_manager),
        "total_warnings": event_counts.get("total_warnings", 0),
        "total_shutoffs": event_counts.get("total_shutoffs", 0),
        "total_power_cycles": event_counts.get("total_power_cycles", 0),
    }

    try:
        intraday = compute_intraday_ratings(hass, config_manager, result["rooms"])
        for room_data in result["rooms"]:
            rid = room_data.get("id")
            if rid:
                room_data["ratings"] = intraday.get(rid)
    except Exception as err:
        _LOGGER.warning("Intraday room ratings embed failed: %s", err)

    connection.send_result(msg["id"], result)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "smart_dashboards/get_daily_history",
        vol.Optional("days", default=30): int,
        vol.Optional("date_start"): str,
        vol.Optional("date_end"): str,
    }
)
@websocket_api.async_response
async def websocket_get_daily_history(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Get daily totals: either last N days, or every day in [date_start, date_end] (billing charts)."""
    config_manager = hass.data[DOMAIN].get("config_manager")
    if not config_manager:
        connection.send_error(msg["id"], "not_ready", "Config manager not initialized")
        return
    date_start = (msg.get("date_start") or "").strip() or None
    date_end = (msg.get("date_end") or "").strip() or None
    if date_start and date_end:
        result = await async_build_billing_daily_history_from_recorder(
            hass, config_manager, date_start, date_end
        )
    else:
        days = min(45, max(1, msg.get("days", 30)))
        result = config_manager.get_daily_history(days=days)
    connection.send_result(msg["id"], result)


def _intraday_point_power_w(hass: HomeAssistant, entity_id: str) -> float:
    """Instantaneous watts for a sensor.* or switch.* (current_power_w) entity."""
    state = hass.states.get(entity_id)
    if not state:
        return 0.0
    if entity_id.startswith("sensor."):
        if state.state in ("unknown", "unavailable", ""):
            return 0.0
        try:
            return float(state.state)
        except (ValueError, TypeError):
            return 0.0
    if entity_id.startswith("switch."):
        try:
            return float(state.attributes.get("current_power_w", 0))
        except (ValueError, TypeError):
            return 0.0
    return 0.0


@websocket_api.websocket_command(
    {
        vol.Required("type"): "smart_dashboards/get_intraday_history",
        vol.Optional("room_id"): str,
        vol.Optional("minutes"): vol.Coerce(int),
        vol.Optional("outlet_index"): vol.Coerce(int),
        vol.Optional("plug_slot"): vol.Coerce(int),
    }
)
@websocket_api.async_response
async def websocket_get_intraday_history(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Get minute-by-minute power history for 24-hour charts."""
    from homeassistant.util import dt as dt_util

    config_manager = hass.data[DOMAIN].get("config_manager")
    if not config_manager:
        connection.send_error(msg["id"], "not_ready", "Config manager not initialized")
        return

    room_id = msg.get("room_id")
    minutes = min(1440, max(1, msg.get("minutes", 1440)))  # Max 24 hours
    outlet_index = msg.get("outlet_index")

    if outlet_index is not None:
        if not room_id:
            connection.send_error(
                msg["id"],
                "invalid_param",
                "room_id is required when outlet_index is set",
            )
            return
        raw_plug = msg.get("plug_slot")
        plug_slot: int | None = None
        if raw_plug is not None:
            try:
                ps = int(raw_plug)
            except (TypeError, ValueError):
                ps = 0
            plug_slot = ps if ps in (1, 2) else None
        tracking_key = config_manager.resolve_outlet_energy_tracking_key(
            room_id, int(outlet_index), plug_slot
        )
        if not tracking_key:
            connection.send_result(
                msg["id"],
                {
                    "timestamps": [],
                    "watts": [],
                    "reference_kwh_today": 0.0,
                },
            )
            return
        hist = config_manager.get_intraday_history(tracking_key, minutes)
        ref_wh = float(config_manager.get_day_energy(tracking_key))
        ref_kwh = ref_wh / 1000.0
        data: dict[str, Any] = {
            "timestamps": [t for t, _ in hist],
            "watts": [w for _, w in hist],
            "reference_kwh_today": ref_kwh,
        }
        if not data["timestamps"]:
            now = dt_util.now().strftime("%Y-%m-%d %H:%M")
            w = 0.0
            if tracking_key.startswith(("sensor.", "switch.")):
                w = _intraday_point_power_w(hass, tracking_key)
            data = {"timestamps": [now], "watts": [w], "reference_kwh_today": ref_kwh}
        connection.send_result(msg["id"], data)
        return

    if room_id:
        # Get room-specific intraday history
        data = config_manager.get_room_intraday_history(room_id, minutes)
    else:
        # Get total intraday history (all rooms)
        data = config_manager.get_total_intraday_history(minutes)
    
    # Ensure at least one data point (current power if no history)
    if not data["timestamps"]:
        now = dt_util.now().strftime("%Y-%m-%d %H:%M")

        current_watts = 0.0
        for room in config_manager.energy_config.get("rooms", []):
            rid = room.get("id", room["name"].lower().replace(" ", "_"))
            if room_id and rid != room_id:
                continue
            for outlet in room.get("outlets", []):
                otype = outlet.get("type") or "outlet"
                if otype == "light":
                    switch_entity = outlet.get("switch_entity")
                    if switch_entity:
                        state = hass.states.get(switch_entity)
                        if state and (state.state or "off").lower() in ("on",):
                            power_ent = (
                                outlet.get("power_sensor_entity")
                                if outlet.get("power_source") == "sensor"
                                else None
                            )
                            if power_ent:
                                current_watts += _intraday_point_power_w(hass, power_ent)
                            else:
                                for le in outlet.get("light_entities") or []:
                                    if isinstance(le, dict) and str(
                                        le.get("entity_id", "")
                                    ).startswith("light."):
                                        current_watts += float(le.get("watts", 0) or 0)
                elif otype in ("vent", "wall_heater"):
                    switch_entity = outlet.get("switch_entity")
                    watts_when_on = float(outlet.get("watts_when_on", 0) or 0)
                    power_ent = (
                        outlet.get("power_sensor_entity")
                        if outlet.get("power_source") == "sensor"
                        else None
                    )
                    if switch_entity:
                        state = hass.states.get(switch_entity)
                        if state and (state.state or "off").lower() in ("on",):
                            if power_ent:
                                current_watts += _intraday_point_power_w(hass, power_ent)
                            elif watts_when_on > 0:
                                current_watts += watts_when_on
                else:
                    for eid in (outlet.get("plug1_entity"), outlet.get("plug2_entity")):
                        if eid:
                            current_watts += _intraday_point_power_w(hass, eid)
        data = {"timestamps": [now], "watts": [current_watts]}

    data["reference_kwh_today"] = (
        config_manager.get_room_day_kwh(room_id)
        if room_id
        else config_manager.get_total_day_kwh()
    )

    connection.send_result(msg["id"], data)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "smart_dashboards/get_intraday_events",
        vol.Optional("room_id"): str,
    }
)
@websocket_api.async_response
async def websocket_get_intraday_events(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Get 24-hour intraday event counts (warnings/shutoffs) for chart display."""
    config_manager = hass.data[DOMAIN].get("config_manager")
    if not config_manager:
        connection.send_error(msg["id"], "not_ready", "Config manager not initialized")
        return
    room_id = msg.get("room_id")
    data = config_manager.get_intraday_events(room_id=room_id)
    connection.send_result(msg["id"], data)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "smart_dashboards/get_event_log",
        vol.Optional("room_id"): str,
        vol.Optional("since_hours"): int,
        vol.Optional("date_start"): str,
        vol.Optional("date_end"): str,
    }
)
@websocket_api.async_response
async def websocket_get_event_log(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Get event log (warnings/shutoffs/cycles) for dashboard (24h) or billing range."""
    config_manager = hass.data[DOMAIN].get("config_manager")
    if not config_manager:
        connection.send_error(msg["id"], "not_ready", "Config manager not initialized")
        return
    room_id = msg.get("room_id")
    date_start = (msg.get("date_start") or "").strip() or None
    date_end = (msg.get("date_end") or "").strip() or None
    if date_start and date_end:
        events, truncated = config_manager.get_event_log(
            room_id=room_id,
            date_start=date_start,
            date_end=date_end,
        )
    else:
        since_hours = msg.get("since_hours", 24)
        events, truncated = config_manager.get_event_log(
            room_id=room_id, since_hours=since_hours
        )
    connection.send_result(
        msg["id"], {"events": events, "truncated": truncated}
    )


def _parse_power_from_state(state_value: str, unit: str | None) -> float:
    """Parse power value to watts. Handles W, kW, mW."""
    if not state_value or state_value in ("unknown", "unavailable"):
        return 0.0
    try:
        val = float(str(state_value).strip())
    except (ValueError, TypeError):
        return 0.0
    if unit == "kW":
        return val * 1000.0
    if unit == "mW":
        return val / 1000.0
    return val  # W or default


def _parse_power_from_state_object(state) -> float:
    """Watts from a recorder State; supports switch.current_power_w on plug-style switches."""
    try:
        eid = state.entity_id
        if eid.startswith("switch.") and state.attributes:
            cp = state.attributes.get("current_power_w")
            if cp is not None and str(cp) not in ("unknown", "unavailable", ""):
                return float(cp)
        unit = state.attributes.get("unit_of_measurement")
        return _parse_power_from_state(state.state, unit)
    except (AttributeError, TypeError, ValueError):
        return 0.0


_SUPPLIER_USAGE_EQ_TOL = 1e-3


def _parse_statistics_usage_float(state_str: str | None) -> float | None:
    """Parse current_usage-style sensor state to float; None if missing or non-numeric."""
    if state_str is None:
        return None
    s = str(state_str).strip()
    if s in ("unknown", "unavailable", ""):
        return None
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def _sync_supplier_usage_plateau_started_at(
    hass: HomeAssistant,
    entity_id: str,
    window_start_utc: datetime,
    window_end_utc: datetime,
    target_kwh: float,
) -> datetime | None:
    """Most recent time in [window_start_utc, window_end_utc] the reading entered the current plateau (≈ target_kWh)."""
    from homeassistant.components.recorder.history import get_significant_states_with_session
    from homeassistant.components.recorder.util import session_scope

    if window_end_utc <= window_start_utc:
        return None
    with session_scope(hass=hass, read_only=True) as session:
        states_dict = get_significant_states_with_session(
            hass,
            session,
            window_start_utc,
            window_end_utc,
            [entity_id],
            None,
            include_start_time_state=True,
            significant_changes_only=True,
            minimal_response=False,
            no_attributes=False,
        )
    states = states_dict.get(entity_id) or []
    states = sorted(states, key=lambda s: s.last_updated)
    tol = _SUPPLIER_USAGE_EQ_TOL
    ts_result: datetime | None = None
    prev_on_plateau = False
    for st in states:
        v = _parse_statistics_usage_float(st.state)
        if v is None:
            prev_on_plateau = False
            continue
        on_plateau = abs(v - target_kwh) <= tol
        if on_plateau and not prev_on_plateau:
            ts_result = st.last_changed
        prev_on_plateau = on_plateau
    return ts_result


def _integrate_power_to_wh_clipped(states: list, start_dt, end_dt) -> float:
    """Step-function W-to-Wh: hold each state's power constant until the next state.

    Back-fill is handled by the caller (include_start_time_state=True injects a state
    before the window). This function adds a synthetic end-of-window marker so that
    constant-power periods with no state changes still accumulate energy through end_dt.
    """
    if not states:
        return 0.0
    states = sorted(states, key=lambda s: s.last_updated)

    # Add synthetic end-of-window state to capture trailing constant power
    last = states[-1]
    if last.last_updated < end_dt:
        from types import SimpleNamespace
        states = list(states)
        states.append(SimpleNamespace(
            state=last.state,
            last_updated=end_dt,
            attributes=getattr(last, 'attributes', {}),
        ))

    total_wh = 0.0

    for i in range(len(states) - 1):
        s1, s2 = states[i], states[i + 1]
        a, b = s1.last_updated, s2.last_updated
        if b <= a:
            continue
        w1 = _parse_power_from_state_object(s1)
        overlap_start = max(a, start_dt)
        overlap_end = min(b, end_dt)
        if overlap_end <= overlap_start:
            continue
        dt_sec = (overlap_end - overlap_start).total_seconds()
        total_wh += w1 * (dt_sec / 3600.0)

    return total_wh


def _is_switch_on_state(state_str: str | None) -> bool:
    if not state_str:
        return False
    return str(state_str).lower() in ("on", "true", "yes", "1")


def _integrate_switch_constant_wh(
    states: list, start_dt, end_dt, watts: float
) -> float:
    """Rectangle rule: constant watts while switch state is on, clipped to [start_dt, end_dt]."""
    if watts <= 0 or not states:
        return 0.0
    states = sorted(states, key=lambda s: s.last_updated)
    total_wh = 0.0
    for i, s in enumerate(states):
        t0 = s.last_updated
        t1 = states[i + 1].last_updated if i + 1 < len(states) else end_dt
        if not _is_switch_on_state(s.state):
            continue
        seg_start = max(t0, start_dt)
        seg_end = min(t1, end_dt)
        if seg_end > seg_start:
            total_wh += watts * (seg_end - seg_start).total_seconds() / 3600.0
    return total_wh


def _enumerate_date_range_iso(start_date: str, end_date: str) -> list[str]:
    """Inclusive local calendar dates YYYY-MM-DD from start_date through end_date."""
    try:
        a = date.fromisoformat(start_date.strip())
        b = date.fromisoformat(end_date.strip())
    except (ValueError, TypeError):
        return []
    if b < a:
        return []
    out: list[str] = []
    d = a
    one = timedelta(days=1)
    while d <= b:
        out.append(d.isoformat())
        d += one
    return out


def _iter_local_calendar_chunks(start_utc: datetime, end_utc: datetime):
    """Yield (chunk_start_utc, chunk_end_utc, day_key) covering [start_utc, end_utc)."""
    if end_utc <= start_utc:
        return
    cur = start_utc
    while cur < end_utc:
        local_cur = dt_util.as_local(cur)
        day0 = local_cur.replace(hour=0, minute=0, second=0, microsecond=0)
        next_day_local = day0 + timedelta(days=1)
        chunk_end_utc = dt_util.as_utc(next_day_local)
        if chunk_end_utc > end_utc:
            chunk_end_utc = end_utc
        day_key = day0.strftime("%Y-%m-%d")
        yield cur, chunk_end_utc, day_key
        cur = chunk_end_utc


def _add_constant_wh_to_date_buckets(
    buckets: dict[str, float], watts: float, t0: datetime, t1: datetime
) -> None:
    if t1 <= t0 or watts == 0:
        return
    for cs, ce, day_key in _iter_local_calendar_chunks(t0, t1):
        buckets[day_key] = buckets.get(day_key, 0.0) + watts * (
            (ce - cs).total_seconds() / 3600.0
        )


def _integrate_power_to_wh_by_local_date(
    states: list, start_dt: datetime, end_dt: datetime
) -> dict[str, float]:
    """Step-function W-to-Wh split by local calendar day.

    Back-fill is handled by the caller (include_start_time_state=True injects a state
    before the window). This function adds a synthetic end-of-window marker so that
    constant-power periods with no state changes still accumulate energy through end_dt.
    """
    buckets: dict[str, float] = {}
    if not states:
        return buckets
    states = sorted(states, key=lambda s: s.last_updated)

    # Add synthetic end-of-window state to capture trailing constant power
    last = states[-1]
    if last.last_updated < end_dt:
        from types import SimpleNamespace
        states = list(states)
        states.append(SimpleNamespace(
            state=last.state,
            last_updated=end_dt,
            attributes=getattr(last, 'attributes', {}),
        ))

    for i in range(len(states) - 1):
        s1, s2 = states[i], states[i + 1]
        a, b = s1.last_updated, s2.last_updated
        if b <= a:
            continue
        w1 = _parse_power_from_state_object(s1)
        overlap_start = max(a, start_dt)
        overlap_end = min(b, end_dt)
        if overlap_end <= overlap_start:
            continue
        _add_constant_wh_to_date_buckets(buckets, w1, overlap_start, overlap_end)

    return buckets


def _integrate_switch_constant_wh_by_local_date(
    states: list, start_dt: datetime, end_dt: datetime, watts: float
) -> dict[str, float]:
    buckets: dict[str, float] = {}
    if watts <= 0 or not states:
        return buckets
    states = sorted(states, key=lambda s: s.last_updated)
    for i, s in enumerate(states):
        t0 = s.last_updated
        t1 = states[i + 1].last_updated if i + 1 < len(states) else end_dt
        if not _is_switch_on_state(s.state):
            continue
        seg_start = max(t0, start_dt)
        seg_end = min(t1, end_dt)
        if seg_end > seg_start:
            _add_constant_wh_to_date_buckets(buckets, watts, seg_start, seg_end)
    return buckets


def _collect_statistics_energy_sources(
    config_manager,
) -> tuple[dict[str, str], list[dict[str, Any]]]:
    """Map plug power entities to rooms; list switch-based constant loads (lights, vents).
    Last mapping wins if the same plug entity appears twice (same as legacy behavior)."""
    entity_to_room: dict[str, str] = {}
    switch_specs: list[dict[str, Any]] = []

    for room in config_manager.energy_config.get("rooms", []):
        room_id = room.get("id", room["name"].lower().replace(" ", "_"))
        for outlet in room.get("outlets", []):
            otype = outlet.get("type", "outlet")
            if otype == "light":
                pe = (
                    outlet.get("power_sensor_entity")
                    if outlet.get("power_source") == "sensor"
                    else None
                )
                if pe and isinstance(pe, str) and pe.strip():
                    entity_to_room[pe.strip()] = room_id
                    continue
                sw = (outlet.get("switch_entity") or "").strip()
                if not sw:
                    continue
                total_w = 0.0
                for le in outlet.get("light_entities") or []:
                    if isinstance(le, dict) and str(le.get("entity_id", "")).startswith(
                        "light."
                    ):
                        total_w += float(le.get("watts", 0) or 0)
                if total_w > 0:
                    switch_specs.append({
                        "room_id": room_id,
                        "switch_entity": sw,
                        "watts": total_w,
                    })
            elif otype in ("vent", "wall_heater"):
                pe = (
                    outlet.get("power_sensor_entity")
                    if outlet.get("power_source") == "sensor"
                    else None
                )
                if pe and isinstance(pe, str) and pe.strip():
                    entity_to_room[pe.strip()] = room_id
                    continue
                sw = (outlet.get("switch_entity") or "").strip()
                w_on = float(outlet.get("watts_when_on", 0) or 0)
                if sw and w_on > 0:
                    switch_specs.append({
                        "room_id": room_id,
                        "switch_entity": sw,
                        "watts": w_on,
                    })
            else:
                # For outlet/single_outlet/stove/microwave/minisplit/fridge:
                # Dedupe: same entity_id as both power_sensor and plug must count once only.
                seen_eids: set[str] = set()
                pe = outlet.get("power_sensor_entity")
                if pe and isinstance(pe, str) and pe.strip():
                    e = pe.strip()
                    entity_to_room[e] = room_id
                    seen_eids.add(e)
                for eid in (outlet.get("plug1_entity"), outlet.get("plug2_entity")):
                    if eid and isinstance(eid, str) and eid.strip():
                        e = eid.strip()
                        if e in seen_eids:
                            continue
                        entity_to_room[e] = room_id
                        seen_eids.add(e)
                ps = (pe.strip() if pe and isinstance(pe, str) else "") or ""
                p1 = (outlet.get("plug1_entity") or "").strip()
                p2 = (outlet.get("plug2_entity") or "").strip()
                if ps and ((p1 and p1 != ps) or (p2 and p2 != ps)):
                    _LOGGER.warning(
                        "Outlet %s in room %s has power_sensor_entity plus different plug "
                        "entities — if they measure the same load, statistics will double count",
                        outlet.get("name", "?"),
                        room_id,
                    )

    return entity_to_room, switch_specs


def _sync_fetch_lts_wh_by_day(
    hass: HomeAssistant,
    entity_ids: list[str],
    start_dt: datetime,
    end_dt: datetime,
) -> dict[str, dict[str, float]]:
    """Fetch Wh per day from Long-Term Statistics (LTS) for energy/power sensors.

    LTS stores hourly aggregations indefinitely even after recorder history is purged.
    This function intelligently handles two types of sensors:

    1. Energy sensors (state_class=total_increasing, device_class=energy):
       - Uses "change" statistic which gives actual energy delta per hour (most accurate)
       - Values are in kWh, converted to Wh

    2. Power sensors (device_class=power or no energy state_class):
       - Uses "mean" statistic (hourly average watts)
       - 1 hour at mean_w Watts = mean_w Wh (approximation)

    Returns: {entity_id: {YYYY-MM-DD: wh, ...}, ...}
    """
    from homeassistant.components.recorder.statistics import statistics_during_period

    if not entity_ids:
        return {}

    tz = dt_util.get_default_time_zone()
    result: dict[str, dict[str, float]] = {}

    # Separate entities by type for optimal querying
    energy_entities: list[str] = []
    power_entities: list[str] = []

    for eid in entity_ids:
        state = hass.states.get(eid)
        if state:
            state_class = state.attributes.get("state_class", "")
            device_class = state.attributes.get("device_class", "")
            unit = state.attributes.get("unit_of_measurement", "")

            # Energy sensors: total_increasing with energy unit (kWh, Wh)
            if state_class == "total_increasing" and (
                device_class == "energy" or unit in ("kWh", "Wh", "MWh")
            ):
                energy_entities.append(eid)
            else:
                # Assume power sensor or treat as power for mean calculation
                power_entities.append(eid)
        else:
            # Unknown state, treat as power sensor
            power_entities.append(eid)

    # Query energy sensors with "change" statistic (exact energy delta per hour)
    if energy_entities:
        try:
            energy_stats = statistics_during_period(
                hass,
                start_time=start_dt,
                end_time=end_dt,
                statistic_ids=set(energy_entities),
                period="hour",
                units={"energy": "kWh"},
                types={"change"},
            )
            for entity_id, hourly_rows in energy_stats.items():
                day_wh: dict[str, float] = {}
                for row in hourly_rows:
                    change_kwh = row.get("change")
                    if change_kwh is None:
                        continue
                    try:
                        change_kwh = float(change_kwh)
                    except (TypeError, ValueError):
                        continue
                    # Skip negative changes (meter reset or error)
                    if change_kwh < 0:
                        continue

                    start_ts = row.get("start")
                    if start_ts is None:
                        continue
                    if isinstance(start_ts, (int, float)):
                        ts_dt = datetime.fromtimestamp(start_ts, tz=tz)
                    elif isinstance(start_ts, datetime):
                        ts_dt = start_ts.astimezone(tz)
                    else:
                        continue

                    # Convert kWh to Wh
                    wh = change_kwh * 1000.0
                    day_key = ts_dt.strftime("%Y-%m-%d")
                    day_wh[day_key] = day_wh.get(day_key, 0.0) + wh

                if day_wh:
                    result[entity_id] = day_wh
        except Exception as err:
            _LOGGER.warning("LTS energy query failed: %s", err)

    # Query power sensors with "mean" statistic (average watts per hour)
    if power_entities:
        try:
            power_stats = statistics_during_period(
                hass,
                start_time=start_dt,
                end_time=end_dt,
                statistic_ids=set(power_entities),
                period="hour",
                units={"power": "W"},
                types={"mean"},
            )
            for entity_id, hourly_rows in power_stats.items():
                day_wh: dict[str, float] = {}
                for row in hourly_rows:
                    mean_w = row.get("mean")
                    if mean_w is None:
                        continue
                    try:
                        mean_w = float(mean_w)
                    except (TypeError, ValueError):
                        continue
                    # Only skip negative values (sensor errors); zero is valid (device off)
                    if mean_w < 0:
                        continue

                    start_ts = row.get("start")
                    if start_ts is None:
                        continue
                    if isinstance(start_ts, (int, float)):
                        ts_dt = datetime.fromtimestamp(start_ts, tz=tz)
                    elif isinstance(start_ts, datetime):
                        ts_dt = start_ts.astimezone(tz)
                    else:
                        continue

                    # 1 hour at mean_w Watts = mean_w Wh
                    wh = mean_w * 1.0
                    day_key = ts_dt.strftime("%Y-%m-%d")
                    day_wh[day_key] = day_wh.get(day_key, 0.0) + wh

                if day_wh:
                    result[entity_id] = day_wh
        except Exception as err:
            _LOGGER.warning("LTS power query failed: %s", err)

    if result:
        total_entities = len(result)
        total_days = sum(len(d) for d in result.values())
        _LOGGER.debug(
            "LTS fallback: fetched %d entities (%d energy, %d power) with %d day-entries total",
            total_entities,
            len(energy_entities),
            len(power_entities),
            total_days,
        )

    return result


def _sync_integrate_entity_wh_total_and_by_day(
    hass: HomeAssistant,
    entity_id: str,
    start_dt,
    end_dt,
) -> tuple[float, dict[str, float]]:
    """Step-function W -> Wh for full range and per local calendar day.

    Back-fill enabled: inject last state before window so constant-power periods are captured.
    No forward-fill, no interpolation/averaging.
    """
    from homeassistant.components.recorder.history import get_significant_states_with_session
    from homeassistant.components.recorder.util import session_scope

    sig_only = not entity_id.startswith("switch.")
    with session_scope(hass=hass, read_only=True) as session:
        states_dict = get_significant_states_with_session(
            hass,
            session,
            start_dt,
            end_dt,
            [entity_id],
            None,
            include_start_time_state=True,
            significant_changes_only=sig_only,
            minimal_response=False,
            no_attributes=False,
        )
    states = states_dict.get(entity_id) or []
    if not states:
        _LOGGER.debug(
            "Recorder returned no states for %s in %s..%s (kWh integration will be 0)",
            entity_id,
            start_dt.isoformat(),
            end_dt.isoformat(),
        )
    total = _integrate_power_to_wh_clipped(states, start_dt, end_dt)
    by_day = _integrate_power_to_wh_by_local_date(states, start_dt, end_dt)

    if total > 0 or by_day:
        _LOGGER.debug(
            "Entity %s integrated: total=%.2f Wh, days=%s",
            entity_id,
            total,
            list(by_day.keys()),
        )
    elif states:
        bad_states = sum(
            1 for s in states if str(s.state) in ("unknown", "unavailable", "")
        )
        first_st = states[0].state if states else "none"
        _LOGGER.debug(
            "Entity %s integrated: 0 Wh (states=%d, bad=%d, first_state=%s)",
            entity_id,
            len(states),
            bad_states,
            first_st,
        )

    return total, by_day


def _sync_compute_plug_wh_total_and_by_day(
    hass: HomeAssistant,
    entity_id: str,
    start_dt,
    end_dt,
) -> tuple[float, dict[str, float], dict[str, Any]]:
    """Energy sensors: sum hourly statistics *change*; else recorder power integration."""
    if entity_statistics_mode(hass, entity_id) == MODE_ENERGY_CHANGE:
        total_wh, by_day, meta = sync_sum_energy_change_wh(
            hass, entity_id, start_dt, end_dt
        )
        return total_wh, by_day, meta
    total_wh, by_day = _sync_integrate_entity_wh_total_and_by_day(
        hass, entity_id, start_dt, end_dt
    )
    return total_wh, by_day, {"method": MODE_POWER_INTEGRATION}


def _sync_integrate_switch_constant_wh_total_and_by_day(
    hass: HomeAssistant,
    switch_entity: str,
    watts: float,
    start_dt,
    end_dt,
) -> tuple[float, dict[str, float]]:
    """Back-fill enabled: inject last state before window so constant-power periods are captured."""
    from homeassistant.components.recorder.history import get_significant_states_with_session
    from homeassistant.components.recorder.util import session_scope

    with session_scope(hass=hass, read_only=True) as session:
        states_dict = get_significant_states_with_session(
            hass,
            session,
            start_dt,
            end_dt,
            [switch_entity],
            None,
            include_start_time_state=True,
            significant_changes_only=True,
            minimal_response=False,
            no_attributes=False,
        )
    states = states_dict.get(switch_entity) or []
    if not states:
        _LOGGER.debug(
            "Recorder returned no states for switch %s in %s..%s (constant-W integration will be 0)",
            switch_entity,
            start_dt.isoformat(),
            end_dt.isoformat(),
        )
    total = _integrate_switch_constant_wh(states, start_dt, end_dt, watts)
    by_day = _integrate_switch_constant_wh_by_local_date(
        states, start_dt, end_dt, watts
    )

    if total > 0 or by_day:
        _LOGGER.debug(
            "Switch %s integrated: total=%.2f Wh, days=%s",
            switch_entity,
            total,
            list(by_day.keys()),
        )
    elif states:
        on_states = sum(1 for s in states if str(s.state).lower() in ("on", "true", "1"))
        first_st = states[0].state if states else "none"
        _LOGGER.debug(
            "Switch %s integrated: 0 Wh (states=%d, on=%d, first_state=%s)",
            switch_entity,
            len(states),
            on_states,
            first_st,
        )

    return total, by_day


def _statistics_cache_ttl_seconds(end_date_str: str, config_manager: Any = None) -> float:
    """Past-only ranges can cache longer; ranges through today match user refresh."""
    from homeassistant.util import dt as dt_util

    today = dt_util.now().strftime("%Y-%m-%d")
    if end_date_str < today:
        return _STATISTICS_CACHE_TTL_PAST
    if config_manager is not None:
        stats = config_manager.energy_config.get("statistics_settings") or {}
        try:
            u = int(stats.get("statistics_refresh_seconds") or 60)
        except (TypeError, ValueError):
            u = 60
        u = max(15, min(600, u))
        # Live TTL aligns with background priming interval so cache stays valid until next refresh
        return float(u)
    return _STATISTICS_CACHE_TTL_LIVE


def _reset_statistics_prime_clock() -> None:
    """Allow immediate cache prime on next tick (e.g. after save_energy)."""
    global _last_stats_prime_at
    _last_stats_prime_at = 0.0


def _clear_recorder_derived_caches() -> None:
    """Statistics + billing charts share recorder integration; clear when energy config changes."""
    _STATISTICS_CACHE.clear()
    _KWH_HISTORY_CACHE.clear()


async def _compute_kwh_from_history(
    hass: HomeAssistant,
    config_manager,
    start_date: str,
    end_date: str,
    *,
    return_breakdown: bool = False,
) -> tuple[float, dict[str, float], dict[str, dict[str, float]], list[dict[str, Any]] | None]:
    """Compute kWh over start_date..end_date for monitored loads.

    Energy sensors use hourly statistics *change*; others use recorder power integration.
    Returns (total_wh, room_wh_map, room_day_wh_map, source_breakdown); breakdown is None
    unless return_breakdown is True. room_day_wh_map[room_id][YYYY-MM-DD] = Wh.
    """
    from homeassistant.util import dt as dt_util

    ds_key = (str(start_date or "").strip(), str(end_date or "").strip())
    if ds_key[0] and ds_key[1] and not return_breakdown:
        now_m = time.monotonic()
        ttl = _statistics_cache_ttl_seconds(ds_key[1], config_manager)
        hit = _KWH_HISTORY_CACHE.get(ds_key)
        if hit:
            cached_at, payload = hit
            if now_m - cached_at < ttl:
                tw, rw, rd = payload
                return tw, rw, rd, None

    entity_to_room, switch_specs = _collect_statistics_energy_sources(config_manager)

    if entity_to_room or switch_specs:
        _LOGGER.debug(
            "Statistics kWh query: %s..%s, %d power entities %s, %d switch specs %s",
            start_date,
            end_date,
            len(entity_to_room),
            list(entity_to_room.keys()),
            len(switch_specs),
            [s["switch_entity"] for s in switch_specs],
        )
    else:
        _LOGGER.debug(
            "Statistics kWh query: %s..%s — no power entities or switch specs configured",
            start_date,
            end_date,
        )

    try:
        start_dt = dt_util.parse_datetime(f"{start_date} 00:00:00")
        end_dt = dt_util.parse_datetime(f"{end_date} 23:59:59")
        if start_dt is None or end_dt is None:
            return 0.0, {}, {}, None
        start_dt = dt_util.as_utc(start_dt)
        end_dt = dt_util.as_utc(end_dt)
    except (ValueError, TypeError):
        return 0.0, {}, {}, None

    now_utc = dt_util.utcnow()
    if start_dt > now_utc:
        return 0.0, {}, {}, None
    end_dt = min(end_dt, now_utc)
    if end_dt < start_dt:
        return 0.0, {}, {}, None

    if not entity_to_room and not switch_specs:
        return 0.0, {}, {}, None

    sem = asyncio.Semaphore(_STATISTICS_QUERY_CONCURRENCY)

    async def one_plug(
        eid: str, room_id: str
    ) -> tuple[str, str, float, dict[str, float], dict[str, Any]]:
        async with sem:
            wh, by_day, meta = await hass.async_add_executor_job(
                _sync_compute_plug_wh_total_and_by_day,
                hass,
                eid,
                start_dt,
                end_dt,
            )
        return eid, room_id, float(wh), by_day, meta

    async def one_switch(
        spec: dict[str, Any],
    ) -> tuple[str, str, float, dict[str, float], dict[str, Any]]:
        async with sem:
            wh, by_day = await hass.async_add_executor_job(
                _sync_integrate_switch_constant_wh_total_and_by_day,
                hass,
                spec["switch_entity"],
                float(spec["watts"]),
                start_dt,
                end_dt,
            )
        meta = {
            "method": "switch_constant",
            "watts": float(spec["watts"]),
        }
        return spec["switch_entity"], spec["room_id"], float(wh), by_day, meta

    coros: list = [one_plug(eid, rid) for eid, rid in entity_to_room.items()]
    coros.extend(one_switch(s) for s in switch_specs)
    if not coros:
        return 0.0, {}, {}, None

    results = await asyncio.gather(*coros)
    room_wh: dict[str, float] = {}
    room_day_wh: dict[str, dict[str, float]] = {}
    total_wh = 0.0

    # Track which days EACH entity has data for (for per-entity LTS fallback)
    entity_days_with_data: dict[str, set[str]] = {}

    source_breakdown: list[dict[str, Any]] = []
    for entity_id, room_id, wh, by_day, meta in results:
        total_wh += wh
        room_wh[room_id] = room_wh.get(room_id, 0.0) + wh
        rmap = room_day_wh.setdefault(room_id, {})
        for dkey, dwh in by_day.items():
            rmap[dkey] = rmap.get(dkey, 0.0) + float(dwh)
        entity_days_with_data[entity_id] = set(by_day.keys())
        if return_breakdown:
            row: dict[str, Any] = {
                "entity_id": entity_id,
                "room_id": room_id,
                "wh": wh,
                "kwh": round(wh / 1000.0, 4),
            }
            row.update(meta)
            source_breakdown.append(row)

    # Generate all expected days in the date range
    all_expected_days: set[str] = set()
    cur = start_dt
    while cur <= end_dt:
        all_expected_days.add(cur.strftime("%Y-%m-%d"))
        cur += timedelta(days=1)

    # PER-ENTITY LTS fallback: Find entities missing days and query LTS for each
    # This is critical: different entities may have different missing days
    entities_needing_lts: list[str] = []
    for eid in entity_to_room:
        if entity_statistics_mode(hass, eid) == MODE_ENERGY_CHANGE:
            continue
        entity_days = entity_days_with_data.get(eid, set())
        missing_for_entity = all_expected_days - entity_days
        if missing_for_entity:
            entities_needing_lts.append(eid)

    if entities_needing_lts:
        _LOGGER.debug(
            "LTS fallback: %d/%d power-integration entities have missing days, querying LTS",
            len(entities_needing_lts),
            len(entity_to_room),
        )

        # Query LTS for ALL entities that have ANY missing days
        lts_result = await hass.async_add_executor_job(
            _sync_fetch_lts_wh_by_day,
            hass,
            entities_needing_lts,
            start_dt,
            end_dt,
        )

        # Merge LTS data for each entity's missing days
        lts_wh_added = 0.0
        lts_days_filled: set[str] = set()
        lts_entities_filled = 0

        for eid, lts_day_wh in lts_result.items():
            room_id = entity_to_room.get(eid)
            if not room_id:
                continue

            # Get days this entity already has from recorder
            entity_recorder_days = entity_days_with_data.get(eid, set())
            # Missing days for THIS entity specifically
            missing_for_entity = all_expected_days - entity_recorder_days

            rmap = room_day_wh.setdefault(room_id, {})
            entity_wh_added = 0.0

            for day_key, wh in lts_day_wh.items():
                # Only add if this day is missing for THIS entity
                if day_key in missing_for_entity:
                    rmap[day_key] = rmap.get(day_key, 0.0) + wh
                    room_wh[room_id] = room_wh.get(room_id, 0.0) + wh
                    total_wh += wh
                    lts_wh_added += wh
                    entity_wh_added += wh
                    lts_days_filled.add(day_key)

            if entity_wh_added > 0:
                lts_entities_filled += 1
            if return_breakdown and entity_wh_added > 0:
                for row in source_breakdown:
                    if row.get("entity_id") == eid:
                        row["lts_fallback_wh_added"] = round(entity_wh_added, 2)
                        break

        if lts_wh_added > 0:
            _LOGGER.debug(
                "LTS fallback added %.2f Wh from %d entities across %d days: %s",
                lts_wh_added,
                lts_entities_filled,
                len(lts_days_filled),
                sorted(lts_days_filled)[:10],
            )

    if ds_key[0] and ds_key[1] and not return_breakdown:
        _KWH_HISTORY_CACHE[ds_key] = (time.monotonic(), (total_wh, room_wh, room_day_wh))

    return total_wh, room_wh, room_day_wh, (
        source_breakdown if return_breakdown else None
    )


async def async_build_billing_daily_history_from_recorder(
    hass: HomeAssistant,
    config_manager,
    date_start: str,
    date_end: str,
) -> dict[str, Any]:
    """Daily Wh for billing charts.

    Primary source: daily_totals.json snapshots (accurate 1s-poll ledger).
    Fallback: recorder integration (step-function, no estimation) for days without a snapshot.
    Merge: when a snapshot day has total_wh ~0 but recorder aggregates Wh > 0 for that day,
    use recorder per-room (and total from recorder sum). Otherwise for past days use
    max(snapshot, recorder) per room and max(snapshot total, recorder sum) for total.
    Today: live day ledger (_build_today_totals).
    """
    today = dt_util.now().strftime("%Y-%m-%d")
    all_room_ids = [
        r.get("id", r["name"].lower().replace(" ", "_"))
        for r in config_manager.energy_config.get("rooms", [])
    ]
    result: dict[str, Any] = {
        "dates": [],
        "sources": [],
        "total_wh": [],
        "total_warnings": [],
        "total_shutoffs": [],
        "total_power_cycles": [],
        "rooms": {
            rid: {"wh": [], "warnings": [], "shutoffs": [], "power_cycles": []}
            for rid in all_room_ids
        },
    }

    effective_end = date_end if date_end <= today else today
    if date_start > effective_end:
        return result

    dates_list = _enumerate_date_range_iso(date_start, effective_end)
    daily_snapshots = config_manager.daily_totals

    # Load recorder for any past day in range so we can fill missing snapshots and correct zero snapshots.
    needs_recorder = any(d < today for d in dates_list)
    room_day_wh_map: dict[str, dict[str, float]] = {}
    if needs_recorder:
        try:
            _, _, room_day_wh_map, _ = await _compute_kwh_from_history(
                hass, config_manager, date_start, effective_end
            )
        except Exception as err:
            _LOGGER.warning("Billing daily history recorder fallback failed: %s", err)

    for d in dates_list:
        if d > today:
            break
        if d == today:
            day_source = "today"
            row = config_manager._build_today_totals()
            total_wh_day = float(row.get("total_wh", 0.0))
            row_rooms = row.get("rooms") or {}
            for rid in all_room_ids:
                wh = float((row_rooms.get(rid) or {}).get("wh", 0.0))
                result["rooms"][rid]["wh"].append(round(wh, 2))
        elif d in daily_snapshots:
            day_source = "snapshot"
            row = daily_snapshots[d]
            total_wh_day = float(row.get("total_wh", 0.0))
            row_rooms = row.get("rooms") or {}
            rec_total = 0.0
            if d < today:
                rec_total = sum(
                    float(room_day_wh_map.get(rid, {}).get(d, 0.0))
                    for rid in all_room_ids
                )
            snap_total_zero = total_wh_day <= 1e-6
            for rid in all_room_ids:
                wh_snap = float((row_rooms.get(rid) or {}).get("wh", 0.0))
                wh_rec = float(room_day_wh_map.get(rid, {}).get(d, 0.0)) if d < today else 0.0
                if d < today and snap_total_zero and rec_total > 1e-6:
                    wh = wh_rec
                elif d < today:
                    wh = max(wh_snap, wh_rec)
                else:
                    wh = wh_snap
                result["rooms"][rid]["wh"].append(round(wh, 2))
            if d < today and snap_total_zero and rec_total > 1e-6:
                total_wh_day = rec_total
            elif d < today:
                total_wh_day = max(total_wh_day, rec_total)
        else:
            day_source = "recorder"
            total_wh_day = sum(
                float(rdays.get(d, 0.0)) for rdays in room_day_wh_map.values()
            )
            for rid in all_room_ids:
                wh = float(room_day_wh_map.get(rid, {}).get(d, 0.0))
                result["rooms"][rid]["wh"].append(round(wh, 2))
            row = {
                "total_wh": 0,
                "total_warnings": 0,
                "total_shutoffs": 0,
                "total_power_cycles": 0,
                "rooms": {},
            }

        result["dates"].append(d)
        result["sources"].append(day_source)
        result["total_wh"].append(round(total_wh_day, 2))
        result["total_warnings"].append(int(row.get("total_warnings", 0)))
        result["total_shutoffs"].append(int(row.get("total_shutoffs", 0)))
        result["total_power_cycles"].append(int(row.get("total_power_cycles", 0)))
        row_rooms = row.get("rooms") or {}
        for rid in all_room_ids:
            rdata = row_rooms.get(rid) or {}
            result["rooms"][rid]["warnings"].append(int(rdata.get("warnings", 0)))
            result["rooms"][rid]["shutoffs"].append(int(rdata.get("shutoffs", 0)))
            result["rooms"][rid]["power_cycles"].append(int(rdata.get("power_cycles", 0)))

    n_dates = len(result["dates"])
    if n_dates:
        if len(result.get("sources", [])) != n_dates:
            _LOGGER.warning(
                "Billing daily history length mismatch: dates=%d sources=%d",
                n_dates,
                len(result.get("sources", [])),
            )
        for key in (
            "total_wh",
            "total_warnings",
            "total_shutoffs",
            "total_power_cycles",
        ):
            if len(result[key]) != n_dates:
                _LOGGER.warning(
                    "Billing daily history length mismatch: dates=%d %s=%d",
                    n_dates,
                    key,
                    len(result[key]),
                )
        for rid in all_room_ids:
            for sub in ("wh", "warnings", "shutoffs", "power_cycles"):
                ln = len(result["rooms"][rid][sub])
                if ln != n_dates:
                    _LOGGER.warning(
                        "Billing daily history length mismatch: dates=%d room=%s %s=%d",
                        n_dates,
                        rid,
                        sub,
                        ln,
                    )

    return result


def _fetch_statistics_sensor_values(
    hass: HomeAssistant,
    config_manager,
) -> dict[str, Any]:
    """Fetch fresh sensor values for statistics (used to refresh stale cache).

    Returns a dict with 'sensor_values' and 'sensor_meta' keys.
    This is a lightweight synchronous function that only reads current states.
    """
    stats_settings = config_manager.energy_config.get("statistics_settings", {})
    sensor_values: dict[str, float | None] = {
        "current_usage": None,
        "projected_usage": None,
        "kwh_cost": None,
    }
    sensor_meta: dict[str, Any] = {
        "supplier_last_updated": None,
        "sensor_states": {},
    }

    usage_last_changed: datetime | None = None
    fallback_last_changed: datetime | None = None

    for key, sensor_key in [
        ("current_usage", "current_usage_sensor"),
        ("projected_usage", "projected_usage_sensor"),
        ("kwh_cost", "kwh_cost_sensor"),
    ]:
        ent = (stats_settings.get(sensor_key) or "").strip()
        if not ent:
            sensor_meta["sensor_states"][key] = {"entity": None, "raw": None}
            continue
        state = hass.states.get(ent)
        if state is None:
            sensor_meta["sensor_states"][key] = {"entity": ent, "raw": "entity_not_found"}
            continue
        raw_state = state.state
        sensor_meta["sensor_states"][key] = {"entity": ent, "raw": raw_state}
        lc = state.last_changed
        if lc:
            if key == "current_usage":
                usage_last_changed = lc
            elif key in ("projected_usage", "kwh_cost"):
                if fallback_last_changed is None or lc > fallback_last_changed:
                    fallback_last_changed = lc
        if raw_state not in ("unknown", "unavailable", ""):
            try:
                val = str(raw_state).strip()
                if key == "kwh_cost":
                    val = val.replace("$", "").replace(",", "").strip()
                sensor_values[key] = float(val)
            except (ValueError, TypeError):
                pass

    supplier_meta_ts = usage_last_changed or fallback_last_changed
    if supplier_meta_ts is not None:
        sensor_meta["supplier_last_updated"] = dt_util.as_local(supplier_meta_ts).isoformat()

    return {
        "sensor_values": sensor_values,
        "sensor_meta": sensor_meta,
    }


async def async_build_statistics_payload(
    hass: HomeAssistant,
    config_manager,
    *,
    date_start: str | None,
    date_end: str | None,
    skip_recorder: bool = False,
) -> dict[str, Any]:
    """Build statistics payload (shared by WebSocket and background cache priming).

    When skip_recorder is True, skip recorder/history integration and supplier plateau
    queries (fast shell for instant UI while JSON cache is filled in background).
    """
    ds = (date_start or "").strip() or None
    de = (date_end or "").strip() or None
    start, end, is_narrowed = config_manager.get_statistics_date_range(
        date_start=ds, date_end=de
    )
    # Defensive fallback: ensure we always have a valid date range
    if not start or not end:
        today = dt_util.now().strftime("%Y-%m-%d")
        start = (dt_util.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        end = today
        is_narrowed = False
        _LOGGER.debug(
            "Statistics date range was empty; using 31-day fallback: %s to %s",
            start,
            end,
        )
    billing_a, billing_b = config_manager.get_billing_date_range()
    period_source = "billing" if (billing_a and billing_b) else "rolling"

    result: dict[str, Any] = {
        "date_start": start,
        "date_end": end,
        "is_narrowed": is_narrowed,
        "period_source": period_source,
        "total_kwh": 0.0,
        "total_warnings": 0,
        "total_shutoffs": 0,
        "total_power_cycles": 0,
        "rooms": [],
        "sensor_values": {
            "current_usage": None,
            "projected_usage": None,
            "kwh_cost": None,
        },
        "sensor_meta": {
            "supplier_last_updated": None,
            "sensor_states": {},
        },
    }

    if billing_a and billing_b:
        await config_manager.record_billing_cycle_if_changed(billing_a, billing_b)

    stats_settings = config_manager.energy_config.get("statistics_settings", {})
    usage_last_changed: datetime | None = None
    fallback_last_changed: datetime | None = None
    for key, sensor_key in [
        ("current_usage", "current_usage_sensor"),
        ("projected_usage", "projected_usage_sensor"),
        ("kwh_cost", "kwh_cost_sensor"),
    ]:
        ent = (stats_settings.get(sensor_key) or "").strip()
        if not ent:
            result["sensor_meta"]["sensor_states"][key] = {"entity": None, "raw": None}
            continue
        state = hass.states.get(ent)
        if state is None:
            result["sensor_meta"]["sensor_states"][key] = {"entity": ent, "raw": "entity_not_found"}
            continue
        raw_state = state.state
        result["sensor_meta"]["sensor_states"][key] = {"entity": ent, "raw": raw_state}
        lc = state.last_changed
        if lc:
            if key == "current_usage":
                usage_last_changed = lc
            elif key in ("projected_usage", "kwh_cost"):
                if fallback_last_changed is None or lc > fallback_last_changed:
                    fallback_last_changed = lc
        if raw_state not in ("unknown", "unavailable", ""):
            try:
                val = str(raw_state).strip()
                if key == "kwh_cost":
                    val = val.replace("$", "").replace(",", "").strip()
                result["sensor_values"][key] = float(val)
            except (ValueError, TypeError):
                pass
    supplier_meta_ts: datetime | None = usage_last_changed or fallback_last_changed
    current_usage_ent = (stats_settings.get("current_usage_sensor") or "").strip()
    cur_usage_val = result["sensor_values"]["current_usage"]
    if current_usage_ent and cur_usage_val is not None and start:
        now_utc = dt_util.utcnow()
        cycle_start_date = billing_a if billing_a else start
        try:
            ws_local = dt_util.parse_datetime(f"{cycle_start_date} 00:00:00")
            if ws_local is not None:
                window_start_utc = dt_util.as_utc(ws_local)
                if window_start_utc < now_utc:
                    plateau_ts = await hass.async_add_executor_job(
                        _sync_supplier_usage_plateau_started_at,
                        hass,
                        current_usage_ent,
                        window_start_utc,
                        now_utc,
                        float(cur_usage_val),
                    )
                    if plateau_ts is not None:
                        supplier_meta_ts = plateau_ts
        except (TypeError, ValueError):
            pass
    if supplier_meta_ts is not None:
        result["sensor_meta"]["supplier_last_updated"] = dt_util.as_local(
            supplier_meta_ts
        ).isoformat()

    if not start or not end:
        return result

    today = dt_util.now().strftime("%Y-%m-%d")

    if skip_recorder:
        total_wh = 0.0
        room_wh_map: dict[str, float] = {}
        room_day_wh_map: dict[str, dict[str, float]] = {}
    else:
        try:
            total_wh, room_wh_map, room_day_wh_map, _ = await _compute_kwh_from_history(
                hass, config_manager, start, end
            )
        except Exception as err:  # recorder not ready or history unavailable
            _LOGGER.warning("Statistics kWh from history failed: %s", err)
            total_wh = 0.0
            room_wh_map = {}
            room_day_wh_map = {}

    daily_totals = config_manager.daily_totals
    if start <= today:
        effective_end = min(end, today)
        stat_day_keys = (
            _enumerate_date_range_iso(start, effective_end)
            if effective_end >= start
            else []
        )
    else:
        stat_day_keys = []

    # Build all_room_ids to match billing logic (ensures we iterate all rooms)
    all_room_ids = [
        r.get("id", r["name"].lower().replace(" ", "_"))
        for r in config_manager.energy_config.get("rooms", [])
    ]

    # Merge daily_totals with recorder/LTS data using the SAME rules as billing:
    # - For today: max(live ledger, recorder) per room — ledger can omit sources statistics includes
    # - For past days with snapshot: use max(snapshot, recorder) per room
    # - When snapshot total is ~0 but recorder has data: prefer recorder
    # - For days without snapshot: leave recorder/LTS data as-is
    for d in stat_day_keys:
        if d == today:
            snap = config_manager._build_today_totals()
            if snap is not None:
                snap_rooms = snap.get("rooms") or {}
                snap_total_wh = float(snap.get("total_wh", 0.0))
                rec_total = sum(
                    float(room_day_wh_map.get(rid, {}).get(d, 0.0))
                    for rid in all_room_ids
                )
                snap_total_zero = snap_total_wh <= 1e-6
                for rid in all_room_ids:
                    wh_snap = float((snap_rooms.get(rid) or {}).get("wh", 0.0))
                    wh_rec = float(room_day_wh_map.get(rid, {}).get(d, 0.0))
                    rmap = room_day_wh_map.setdefault(rid, {})
                    if snap_total_zero and rec_total > 1e-6:
                        rmap[d] = wh_rec
                    else:
                        rmap[d] = max(wh_snap, wh_rec)
        elif d in daily_totals:
            # Past day with snapshot: apply max merge logic (same as billing)
            snap = daily_totals[d]
            snap_total_wh = float(snap.get("total_wh", 0.0))
            snap_rooms = snap.get("rooms") or {}

            # Sum recorder/LTS values for this day across all rooms
            rec_total = sum(
                float(room_day_wh_map.get(rid, {}).get(d, 0.0))
                for rid in all_room_ids
            )
            snap_total_zero = snap_total_wh <= 1e-6

            for rid in all_room_ids:
                wh_snap = float((snap_rooms.get(rid) or {}).get("wh", 0.0))
                wh_rec = float(room_day_wh_map.get(rid, {}).get(d, 0.0))
                rmap = room_day_wh_map.setdefault(rid, {})

                if snap_total_zero and rec_total > 1e-6:
                    # Snapshot total is ~0 but recorder has data: use recorder
                    rmap[d] = wh_rec
                else:
                    # Use max of snapshot and recorder
                    rmap[d] = max(wh_snap, wh_rec)
        # else: no snapshot for this day, leave room_day_wh_map from recorder/LTS

    # Rebuild totals from merged room_day_wh_map
    room_wh_map = {}
    total_wh = 0.0
    for rid, dmap in room_day_wh_map.items():
        s = sum(dmap.values())
        room_wh_map[rid] = s
        total_wh += s

    total_kwh = total_wh / 1000.0 if total_wh else 0.0
    n_stat_days = len(stat_day_keys)

    def _room_daily_kwh_stats(rid: str, kwh_total: float) -> dict[str, float]:
        """High/low kWh per local day in elapsed window; avg = load / days elapsed (inclusive)."""
        if not stat_day_keys:
            return {
                "daily_high_kwh": 0.0,
                "daily_low_kwh": 0.0,
                "daily_avg_kwh": 0.0,
            }
        rdays = room_day_wh_map.get(rid, {})
        daily_kwh = [rdays.get(d, 0.0) / 1000.0 for d in stat_day_keys]
        return {
            "daily_high_kwh": round(max(daily_kwh), 2),
            "daily_low_kwh": round(min(daily_kwh), 2),
            "daily_avg_kwh": round(kwh_total / n_stat_days, 2),
        }

    all_dates = set(daily_totals.keys())
    if start <= today <= end:
        all_dates.add(today)
    dates_sorted = sorted(all_dates)
    range_dates = [d for d in dates_sorted if start <= d <= end]

    total_warnings = 0
    total_shutoffs = 0
    total_power_cycles = 0
    room_sums: dict[str, dict[str, Any]] = {}

    for rid in room_wh_map:
        room_sums[rid] = {
            "kwh": room_wh_map[rid] / 1000.0,
            "warnings": 0,
            "shutoffs": 0,
            "power_cycles": 0,
        }

    for d in range_dates:
        if d == today:
            row = config_manager._build_today_totals()
        else:
            row = daily_totals.get(d, {})
        total_warnings += int(row.get("total_warnings", 0))
        total_shutoffs += int(row.get("total_shutoffs", 0))
        total_power_cycles += int(row.get("total_power_cycles", 0))
        row_rooms = row.get("rooms") or {}
        for rid, rdata in row_rooms.items():
            if rid not in room_sums:
                room_sums[rid] = {
                    "kwh": 0.0,
                    "warnings": 0,
                    "shutoffs": 0,
                    "power_cycles": 0,
                }
            room_sums[rid]["warnings"] += int(rdata.get("warnings", 0))
            room_sums[rid]["shutoffs"] += int(rdata.get("shutoffs", 0))
            room_sums[rid]["power_cycles"] += int(rdata.get("power_cycles", 0))
    result["total_kwh"] = round(total_kwh, 2)
    result["total_warnings"] = total_warnings
    result["total_shutoffs"] = total_shutoffs
    result["total_power_cycles"] = total_power_cycles

    rooms_config = config_manager.energy_config.get("rooms", [])
    for room in rooms_config:
        rid = room.get("id", room["name"].lower().replace(" ", "_"))
        name = room.get("name", rid)
        rsum = room_sums.get(
            rid,
            {"kwh": 0.0, "warnings": 0, "shutoffs": 0, "power_cycles": 0},
        )
        kwh = round(rsum["kwh"], 2)
        pct = round((kwh / total_kwh * 100) if total_kwh > 0 else 0, 1)
        result["rooms"].append({
            "id": rid,
            "name": name,
            "kwh": kwh,
            "pct": pct,
            "warnings": rsum["warnings"],
            "shutoffs": rsum["shutoffs"],
            "power_cycles": rsum.get("power_cycles", 0),
            **_room_daily_kwh_stats(rid, kwh),
        })

    for rid in room_sums:
        if not any(r["id"] == rid for r in result["rooms"]):
            rsum = room_sums[rid]
            kwh = round(rsum["kwh"], 2)
            pct = round((kwh / total_kwh * 100) if total_kwh > 0 else 0, 1)
            result["rooms"].append({
                "id": rid,
                "name": rid.replace("_", " ").title(),
                "kwh": kwh,
                "pct": pct,
                "warnings": rsum["warnings"],
                "shutoffs": rsum["shutoffs"],
                "power_cycles": rsum.get("power_cycles", 0),
                **_room_daily_kwh_stats(rid, kwh),
            })

    try:
        room_event_totals = {
            rid: {
                "warnings": int(rsum["warnings"]),
                "shutoffs": int(rsum["shutoffs"]),
                "power_cycles": int(rsum.get("power_cycles", 0)),
            }
            for rid, rsum in room_sums.items()
        }
        monthly = compute_monthly_ratings(
            hass,
            config_manager,
            stat_day_keys=stat_day_keys,
            room_wh_totals=dict(room_wh_map),
            room_day_wh=dict(room_day_wh_map),
            room_event_totals=room_event_totals,
        )
        for r in result["rooms"]:
            rid = r.get("id")
            if rid:
                r["ratings"] = monthly.get(rid)
    except Exception as err:
        _LOGGER.warning("Monthly room ratings embed failed: %s", err)

    return result


async def _prime_statistics_cache(hass: HomeAssistant) -> None:
    """Build statistics, save to JSON, and fire event for live UI push."""
    config_manager = hass.data[DOMAIN].get("config_manager")
    if not config_manager:
        return
    try:
        result = await async_build_statistics_payload(
            hass, config_manager, date_start=None, date_end=None
        )
    except Exception as err:
        _LOGGER.warning("Statistics cache prime failed: %s", err)
        return
    start = result.get("date_start") or ""
    end = result.get("date_end") or ""
    if not start or not end:
        return
    # Save to JSON for instant page load (omit UI-only flags)
    to_save = dict(result)
    to_save.pop("statistics_pending", None)
    try:
        daily_history = await async_build_billing_daily_history_from_recorder(
            hass, config_manager, start, end
        )
        to_save["daily_history"] = daily_history
        to_save["daily_history_range"] = {"date_start": start, "date_end": end}
    except Exception as err:
        _LOGGER.warning("Statistics daily_history for cache failed: %s", err)
        to_save.pop("daily_history", None)
        to_save.pop("daily_history_range", None)
    await config_manager.async_save_statistics_cache(to_save)
    # Fire event so frontend subscribers get live push
    hass.bus.async_fire("smart_dashboards_statistics_updated", {"data": to_save})


async def _statistics_cache_prime_tick(hass: HomeAssistant, _now: datetime) -> None:
    """Respect statistics_refresh_seconds between primes; 15s scheduler tick."""
    global _last_stats_prime_at

    config_manager = hass.data[DOMAIN].get("config_manager")
    if not config_manager:
        return
    stats = config_manager.energy_config.get("statistics_settings") or {}
    try:
        refresh = int(stats.get("statistics_refresh_seconds") or 60)
    except (TypeError, ValueError):
        refresh = 60
    refresh = max(15, min(600, refresh))
    now_m = time.monotonic()
    if _last_stats_prime_at > 0 and now_m - _last_stats_prime_at < refresh - 0.25:
        return
    _last_stats_prime_at = now_m
    await _prime_statistics_cache(hass)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "smart_dashboards/get_statistics",
        vol.Optional("date_start"): str,
        vol.Optional("date_end"): str,
    }
)
@websocket_api.async_response
async def websocket_get_statistics(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Get aggregated statistics for a date range.
    
    For default date range (no date_start/date_end), always load from JSON file
    for instant response. Background task keeps JSON updated.
    """
    config_manager = hass.data[DOMAIN].get("config_manager")
    if not config_manager:
        connection.send_error(msg["id"], "not_ready", "Config manager not initialized")
        return

    date_start = (msg.get("date_start") or "").strip() or None
    date_end = (msg.get("date_end") or "").strip() or None
    billing_a, billing_b = config_manager.get_billing_date_range()
    period_source = "billing" if (billing_a and billing_b) else "rolling"

    # For default date range, always load from JSON file (instant, no computation)
    if date_start is None and date_end is None:
        json_cache = config_manager.statistics_cache_data
        if json_cache:
            # Always fetch fresh sensor values (they may have become available since cache was saved)
            fresh_sensors = _fetch_statistics_sensor_values(hass, config_manager)
            merged = {**json_cache, "period_source": period_source}
            merged["sensor_values"] = fresh_sensors["sensor_values"]
            merged["sensor_meta"] = fresh_sensors["sensor_meta"]
            connection.send_result(msg["id"], merged)
            return
        # No snapshot yet: return fast shell (no recorder) and prime full build in background
        shell = await async_build_statistics_payload(
            hass,
            config_manager,
            date_start=None,
            date_end=None,
            skip_recorder=True,
        )
        shell["statistics_pending"] = True
        connection.send_result(
            msg["id"], {**shell, "period_source": period_source}
        )
        hass.async_create_task(_prime_statistics_cache(hass))
        return

    # Custom date range: compute fresh (no caching for custom ranges)
    result = await async_build_statistics_payload(
        hass, config_manager, date_start=date_start, date_end=date_end
    )
    connection.send_result(msg["id"], result)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "smart_dashboards/subscribe_statistics",
    }
)
@callback
def websocket_subscribe_statistics(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Subscribe to statistics updates for live push to frontend."""

    @callback
    def forward_statistics_update(event) -> None:
        """Forward statistics update event to WebSocket."""
        data = event.data.get("data", {})
        billing_a, billing_b = None, None
        config_manager = hass.data.get(DOMAIN, {}).get("config_manager")
        if config_manager:
            billing_a, billing_b = config_manager.get_billing_date_range()
        period_source = "billing" if (billing_a and billing_b) else "rolling"
        connection.send_message(
            websocket_api.event_message(
                msg["id"], {**data, "period_source": period_source}
            )
        )

    unsub = hass.bus.async_listen(
        "smart_dashboards_statistics_updated", forward_statistics_update
    )
    connection.subscriptions[msg["id"]] = unsub
    connection.send_result(msg["id"])


@websocket_api.websocket_command(
    {
        vol.Required("type"): "smart_dashboards/subscribe_hard_refresh_progress",
    }
)
@callback
def websocket_subscribe_hard_refresh_progress(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Subscribe to hard refresh progress events for live broadcast to all clients."""

    @callback
    def forward_progress(event) -> None:
        """Forward hard refresh progress event to WebSocket."""
        connection.send_message(
            websocket_api.event_message(msg["id"], event.data)
        )

    unsub = hass.bus.async_listen(
        "smart_dashboards_hard_refresh_progress", forward_progress
    )
    connection.subscriptions[msg["id"]] = unsub
    connection.send_result(msg["id"])


@websocket_api.websocket_command(
    {
        vol.Required("type"): "smart_dashboards/get_entities_by_area",
        vol.Required("area_id"): str,
    }
)
@websocket_api.async_response
async def websocket_get_entities_by_area(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Get power sensor entities for a specific area/room."""
    from homeassistant.helpers import entity_registry, device_registry, area_registry

    area_id = msg["area_id"].lower().replace(" ", "_").replace("'", "")
    
    ent_reg = entity_registry.async_get(hass)
    dev_reg = device_registry.async_get(hass)
    area_reg = area_registry.async_get(hass)

    # Find matching area
    target_area = None
    for area in area_reg.async_list_areas():
        area_normalized = area.name.lower().replace(" ", "_").replace("'", "")
        if area_normalized == area_id or area.id == area_id:
            target_area = area
            break

    if not target_area:
        connection.send_result(msg["id"], {"outlets": [], "area_found": False})
        return

    # Find all power sensors in this area
    outlets = []
    for entity in ent_reg.entities.values():
        entity_area = None
        
        # Check entity's direct area assignment
        if entity.area_id == target_area.id:
            entity_area = target_area.id
        # Check device's area assignment
        elif entity.device_id:
            device = dev_reg.async_get(entity.device_id)
            if device and device.area_id == target_area.id:
                entity_area = target_area.id

        if entity_area and entity.entity_id.startswith("sensor."):
            state = hass.states.get(entity.entity_id)
            if state:
                unit = state.attributes.get("unit_of_measurement", "")
                # Check if it's a power sensor
                if "power" in entity.entity_id.lower() or unit in ("W", "kW", "mW"):
                    friendly_name = state.attributes.get("friendly_name", entity.entity_id)
                    outlets.append({
                        "entity_id": entity.entity_id,
                        "friendly_name": friendly_name,
                        "unit": unit,
                    })

    connection.send_result(msg["id"], {"outlets": outlets, "area_found": True, "area_name": target_area.name})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "smart_dashboards/get_areas",
    }
)
@websocket_api.async_response
async def websocket_get_areas(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Get all areas/rooms in Home Assistant."""
    from homeassistant.helpers import area_registry

    area_reg = area_registry.async_get(hass)
    areas = []
    
    for area in area_reg.async_list_areas():
        areas.append({
            "id": area.id,
            "name": area.name,
        })

    connection.send_result(msg["id"], {"areas": areas})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "smart_dashboards/verify_passcode",
        vol.Required("passcode"): str,
    }
)
@websocket_api.async_response
async def websocket_verify_passcode(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Verify the settings passcode."""
    # Get stored passcode from integration options
    stored_passcode = hass.data[DOMAIN].get("options", {}).get("settings_passcode", "0000")
    entered_passcode = msg["passcode"]
    
    if entered_passcode == stored_passcode:
        connection.send_result(msg["id"], {"valid": True})
    else:
        connection.send_result(msg["id"], {"valid": False})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "smart_dashboards/check_toggle_auth",
        vol.Required("room_id"): str,
    }
)
@websocket_api.async_response
async def websocket_check_toggle_auth(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Check if the current user can toggle switches in a room."""
    is_admin = _ws_connection_user_is_admin(connection)
    config_manager = hass.data[DOMAIN].get("config_manager")
    if not config_manager:
        connection.send_result(
            msg["id"],
            {"authorized": False, "error": "config_not_ready", "is_admin": is_admin},
        )
        return

    room_id = msg["room_id"]
    rooms = config_manager.energy_config.get("rooms", [])
    room = next((r for r in rooms if r.get("id") == room_id), None)

    if not room:
        connection.send_result(
            msg["id"],
            {"authorized": False, "error": "room_not_found", "is_admin": is_admin},
        )
        return

    user = connection.user
    user_name = user.name if user else "Guest"

    person_ent = room.get("presence_person_entity")
    if not person_ent:
        connection.send_result(
            msg["id"],
            {
                "authorized": True,
                "user_name": user_name,
                "requires_tts": True,
                "is_admin": is_admin,
            },
        )
        return

    person_state = hass.states.get(person_ent)
    person_name = (
        person_state.attributes.get("friendly_name", "")
        if person_state
        else ""
    )

    authorized = user_name.lower().strip() == person_name.lower().strip()
    connection.send_result(
        msg["id"],
        {
            "authorized": authorized,
            "user_name": user_name,
            "requires_tts": not authorized,
            "room_person": person_name,
            "is_admin": is_admin,
        },
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "smart_dashboards/set_room_budget_boost_days",
        vol.Required("room_id"): str,
        vol.Required("weekdays"): vol.All(
            cv.ensure_list,
            [vol.All(vol.Coerce(int), vol.Range(min=0, max=6))],
        ),
    }
)
@websocket_api.async_response
async def websocket_set_room_budget_boost_days(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Set per-room budget boost weekdays (assignee or admin; 48h cooldown for assignee)."""
    config_manager = hass.data[DOMAIN].get("config_manager")
    if not config_manager:
        connection.send_error(msg["id"], "not_ready", "Config manager not initialized")
        return

    room_id = str(msg["room_id"]).strip()
    new_days = _normalize_room_budget_boost_weekdays(msg.get("weekdays") or [])
    rooms = config_manager.energy_config.get("rooms", [])
    room = next((r for r in rooms if r.get("id") == room_id), None)
    if not room:
        connection.send_error(msg["id"], "not_found", "Room not found")
        return

    person_ent = room.get("presence_person_entity")
    if not person_ent or not str(person_ent).strip().lower().startswith("person."):
        connection.send_error(
            msg["id"],
            "invalid_room",
            "This room has no assigned person",
        )
        return

    if not _room_budget_boost_assignee_only(hass, connection, str(person_ent)):
        connection.send_error(
            msg["id"],
            "unauthorized",
            "Only the assigned person can set boost budget days for this room.",
        )
        return

    old_days = _normalize_room_budget_boost_weekdays(room.get("room_budget_boost_weekdays"))
    if old_days == new_days:
        connection.send_result(msg["id"], {"success": True, "room_budget_boost_weekdays": new_days})
        return

    raw_at = room.get("room_budget_boost_weekdays_changed_at")
    if raw_at:
        last_dt = dt_util.parse_datetime(str(raw_at))
        if last_dt is not None:
            last_utc = dt_util.as_utc(last_dt)
            if dt_util.utcnow() - last_utc < timedelta(hours=48):
                connection.send_error(
                    msg["id"],
                    "cooldown",
                    "Budget boost days can only be changed once every 48 hours. Try again later.",
                )
                return

    energy = deepcopy(dict(config_manager.energy_config))
    updated = False
    target_rid = room.get("id")
    for r in energy.get("rooms", []):
        if r.get("id") == target_rid:
            r["room_budget_boost_weekdays"] = new_days
            r["room_budget_boost_weekdays_changed_at"] = (
                dt_util.utcnow().replace(microsecond=0).isoformat()
            )
            updated = True
            break
    if not updated:
        connection.send_error(msg["id"], "not_found", "Room not found")
        return

    try:
        await config_manager.async_update_energy(energy)
        _reset_statistics_prime_clock()
        _clear_recorder_derived_caches()
        hass.async_create_task(_prime_statistics_cache(hass))
        hass.async_create_task(async_reschedule_efficiency_digest(hass))
    except Exception as e:
        _LOGGER.exception("set_room_budget_boost_days failed: %s", e)
        connection.send_error(msg["id"], "save_failed", str(e))
        return

    connection.send_result(
        msg["id"],
        {"success": True, "room_budget_boost_weekdays": new_days},
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "smart_dashboards/toggle_switch",
        vol.Required("entity_id"): str,
        vol.Optional("room_id"): str,
        vol.Optional("outlet_name"): str,
        vol.Optional("plug_name"): str,
        vol.Optional("announce_tts"): bool,
    }
)
@websocket_api.async_response
async def websocket_toggle_switch(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Toggle a switch entity with optional TTS announcement."""
    entity_id = msg["entity_id"]
    room_id = msg.get("room_id")
    outlet_name = msg.get("outlet_name", "")
    plug_name = msg.get("plug_name", "")
    announce_tts = msg.get("announce_tts", False)

    if not entity_id or not entity_id.startswith("switch."):
        connection.send_error(msg["id"], "invalid_entity", "Not a valid switch entity")
        return

    state = hass.states.get(entity_id)
    if state is None:
        connection.send_error(msg["id"], "entity_not_found", f"Switch {entity_id} not found")
        return

    user = connection.user
    user_name = user.name if user else "Someone"

    current_state = state.state
    new_state = "off" if current_state == "on" else "on"

    # Block manual wall heater ON when warmer than heater_on_below_temperature (same rule as automation).
    if new_state == "on" and room_id:
        cm = hass.data.get(DOMAIN, {}).get("config_manager")
        if cm:
            rooms_cfg = cm.energy_config.get("rooms", [])
            room_cfg = next((r for r in rooms_cfg if r.get("id") == room_id), None)
            if room_cfg:
                for out in room_cfg.get("outlets") or []:
                    if out.get("type") != "wall_heater":
                        continue
                    if (out.get("switch_entity") or "").strip() != entity_id:
                        continue
                    hwe = str(out.get("heater_weather_entity") or "").strip()
                    outdoor = (
                        outdoor_temperature_from_entity(hass, hwe) if hwe else None
                    )
                    eff_on, _eff_c, _boost = resolve_wall_heater_effective_temperatures(
                        out, outdoor
                    )
                    try:
                        threshold = float(eff_on)
                    except (TypeError, ValueError):
                        threshold = 65.0
                    te = str(out.get("heater_temperature_entity") or "").strip()
                    temp = (
                        _parse_temperature_sensor_state(hass, te)
                        if te.startswith("sensor.")
                        else None
                    )
                    if temp is not None and int(temp) > int(threshold):
                        connection.send_error(
                            msg["id"],
                            "heater_too_warm",
                            f"It's already {int(temp)}° in here—the heater only turns on below {int(threshold)}°.",
                        )
                        return
                    door_ent = str(out.get("heater_door_sensor_entity") or "").strip()
                    window_ent = str(out.get("heater_window_sensor_entity") or "").strip()
                    blocker = None
                    if door_ent.startswith("binary_sensor."):
                        ds = hass.states.get(door_ent)
                        if ds and ds.state == "on":
                            blocker = "door"
                    if not blocker and window_ent.startswith("binary_sensor."):
                        ws = hass.states.get(window_ent)
                        if ws and ws.state == "on":
                            blocker = "window"
                    if blocker:
                        room_name = room_cfg.get("name", room_id)
                        connection.send_error(
                            msg["id"],
                            "heater_blocked_open",
                            f"{room_name} heater cannot turn on—the {blocker} is open.",
                        )
                        return
                    break

    try:
        ctx = Context(user_id=user.id) if user else None
        await hass.services.async_call(
            "switch",
            f"turn_{new_state}",
            {"entity_id": entity_id},
            blocking=False,
            context=ctx,
        )

        if announce_tts and room_id:
            config_manager = hass.data[DOMAIN].get("config_manager")
            if config_manager:
                rooms = config_manager.energy_config.get("rooms", [])
                room = next((r for r in rooms if r.get("id") == room_id), None)
                if room:
                    media_player = (room.get("media_player") or "").strip()
                    if media_player.startswith("media_player."):
                        tts_settings = config_manager.energy_config.get("tts_settings") or {}
                        prefix = tts_settings.get("prefix", "")
                        action_word = "on" if new_state == "on" else "off"
                        appliance_desc = outlet_name
                        if plug_name:
                            appliance_desc = f"{outlet_name} {plug_name}"
                        tts_msg = f"{prefix}. {user_name} turned {action_word} {appliance_desc}".strip()
                        if tts_msg.startswith("."):
                            tts_msg = tts_msg[1:].strip()
                        try:
                            from .tts_queue import async_send_tts_or_queue
                            vol_level = float(room.get("volume", 0.7) or 0.7)
                            await async_send_tts_or_queue(
                                hass,
                                media_player=media_player,
                                message=tts_msg,
                                language=tts_settings.get("language"),
                                volume=vol_level,
                                tts_settings=tts_settings,
                                room=room,
                            )
                        except Exception as tts_err:
                            _LOGGER.warning("TTS announcement failed: %s", tts_err)

        connection.send_result(msg["id"], {"state": new_state, "user_name": user_name})
    except Exception as e:
        _LOGGER.error("Failed to toggle switch %s: %s", entity_id, e)
        connection.send_error(msg["id"], "toggle_failed", str(e))


@websocket_api.websocket_command(
    {
        vol.Required("type"): "smart_dashboards/get_switches",
        vol.Optional("area_id"): str,
    }
)
@websocket_api.async_response
async def websocket_get_switches(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Get all switch entities, optionally filtered by area."""
    from homeassistant.helpers import entity_registry, device_registry, area_registry

    area_id = msg.get("area_id")
    
    switches = []
    
    if area_id:
        # Filter by area
        ent_reg = entity_registry.async_get(hass)
        dev_reg = device_registry.async_get(hass)
        area_reg = area_registry.async_get(hass)

        # Find matching area
        target_area = None
        for area in area_reg.async_list_areas():
            area_normalized = area.name.lower().replace(" ", "_").replace("'", "")
            if area_normalized == area_id or area.id == area_id:
                target_area = area
                break

        if target_area:
            for entity in ent_reg.entities.values():
                entity_area = None
                
                if entity.area_id == target_area.id:
                    entity_area = target_area.id
                elif entity.device_id:
                    device = dev_reg.async_get(entity.device_id)
                    if device and device.area_id == target_area.id:
                        entity_area = target_area.id

                if entity_area and entity.entity_id.startswith("switch."):
                    state = hass.states.get(entity.entity_id)
                    if state:
                        friendly_name = state.attributes.get("friendly_name", entity.entity_id)
                        switches.append({
                            "entity_id": entity.entity_id,
                            "friendly_name": friendly_name,
                        })
    else:
        # Get all switches
        for state in hass.states.async_all():
            if state.entity_id.startswith("switch."):
                friendly_name = state.attributes.get("friendly_name", state.entity_id)
                switches.append({
                    "entity_id": state.entity_id,
                    "friendly_name": friendly_name,
                })

    connection.send_result(msg["id"], {"switches": switches})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "smart_dashboards/get_breaker_data",
    }
)
@websocket_api.async_response
async def websocket_get_breaker_data(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Get current power readings for all breaker lines."""
    config_manager = hass.data[DOMAIN].get("config_manager")
    if not config_manager:
        connection.send_error(msg["id"], "not_ready", "Config manager not initialized")
        return

    result: dict[str, Any] = {"breaker_lines": []}

    for breaker in config_manager.energy_config.get("breaker_lines", []):
        breaker_id = breaker.get("id")
        outlets = config_manager.get_outlets_for_breaker(breaker_id)
        
        breaker_data = {
            "id": breaker_id,
            "name": breaker.get("name", "Breaker"),
            "color": breaker.get("color", "#03a9f4"),
            "max_load": breaker.get("max_load", 2400),
            "threshold": breaker.get("threshold", 0),
            "total_watts": 0,
            "total_day_wh": 0,
            "outlets": [],
        }

        max_load = breaker.get("max_load", 2400)

        # Calculate total power for this breaker and get outlet details
        for outlet in outlets:
            outlet_data = {
                "name": outlet.get("outlet_name", "Outlet"),
                "room_name": outlet.get("room_name", ""),
                "plug1_watts": 0,
                "plug2_watts": 0,
                "total_watts": 0,
                "percentage": 0,
            }
            
            if outlet.get("plug1_entity"):
                watts = _get_power_value(hass, outlet["plug1_entity"])
                day_wh = config_manager.get_day_energy(outlet["plug1_entity"])
                outlet_data["plug1_watts"] = watts
                breaker_data["total_watts"] += watts
                breaker_data["total_day_wh"] += day_wh
                
            if outlet.get("plug2_entity"):
                watts = _get_power_value(hass, outlet["plug2_entity"])
                day_wh = config_manager.get_day_energy(outlet["plug2_entity"])
                outlet_data["plug2_watts"] = watts
                breaker_data["total_watts"] += watts
                breaker_data["total_day_wh"] += day_wh
            
            outlet_data["total_watts"] = outlet_data["plug1_watts"] + outlet_data["plug2_watts"]
            outlet_data["percentage"] = round((outlet_data["total_watts"] / max_load * 100) if max_load > 0 else 0, 1)
            breaker_data["outlets"].append(outlet_data)

        breaker_data["total_watts"] = round(breaker_data["total_watts"], 1)
        breaker_data["total_day_wh"] = round(breaker_data["total_day_wh"], 2)
        result["breaker_lines"].append(breaker_data)

    connection.send_result(msg["id"], result)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "smart_dashboards/test_trip_breaker",
        vol.Required("breaker_id"): str,
    }
)
@websocket_api.async_response
async def websocket_test_trip_breaker(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Test trip a breaker line - toggle all switches (like outlet test button)."""
    config_manager = hass.data[DOMAIN].get("config_manager")
    if not config_manager:
        connection.send_error(msg["id"], "not_ready", "Config manager not initialized")
        return

    breaker_id = msg["breaker_id"]
    outlets = config_manager.get_outlets_for_breaker(breaker_id)
    
    # Collect all switch entity IDs
    switch_entities = []
    for outlet in outlets:
        if outlet.get("plug1_switch") and outlet["plug1_switch"].startswith("switch."):
            switch_entities.append(outlet["plug1_switch"])
        if outlet.get("plug2_switch") and outlet["plug2_switch"].startswith("switch."):
            switch_entities.append(outlet["plug2_switch"])
    
    if not switch_entities:
        connection.send_error(msg["id"], "no_switches", "No switches found for this breaker")
        return
    
    try:
        # Turn off all switches
        await hass.services.async_call(
            "switch",
            "turn_off",
            {"entity_id": switch_entities},
            blocking=True,
        )
        
        # Wait 5 seconds
        await asyncio.sleep(5)
        
        # Turn all switches back on
        await hass.services.async_call(
            "switch",
            "turn_on",
            {"entity_id": switch_entities},
            blocking=True,
        )
        
        connection.send_result(msg["id"], {
            "success": True,
            "total_switches": len(switch_entities),
            "message": "Test trip completed: switches turned off, waited 5 seconds, turned back on",
        })
    except Exception as e:
        _LOGGER.error("Test trip breaker failed: %s", e)
        connection.send_error(msg["id"], "trip_failed", str(e))


@websocket_api.websocket_command(
    {
        vol.Required("type"): "smart_dashboards/get_stove_data",
    }
)
@websocket_api.async_response
async def websocket_get_stove_data(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Get current stove safety status and timer information (first configured stove)."""
    config_manager = hass.data[DOMAIN].get("config_manager")
    if not config_manager:
        connection.send_error(msg["id"], "not_ready", "Config manager not initialized")
        return

    energy_monitor = hass.data[DOMAIN].get("energy_monitor")
    if not energy_monitor:
        connection.send_error(msg["id"], "not_ready", "Energy monitor not initialized")
        return

    # Get first configured stove from device config
    stove_config = None
    for room in config_manager.energy_config.get("rooms", []):
        for outlet in room.get("outlets", []):
            if outlet.get("type") == "stove" and outlet.get("plug1_entity") and outlet.get("presence_sensor"):
                stove_config = outlet
                break
        if stove_config:
            break

    stove_plug_entity = stove_config.get("plug1_entity") if stove_config else None
    presence_sensor = stove_config.get("presence_sensor") if stove_config else None
    stove_power_threshold = int(stove_config.get("stove_power_threshold", 100)) if stove_config else 100
    cooking_time_minutes = int(stove_config.get("cooking_time_minutes", 15)) if stove_config else 15
    final_warning_seconds = int(stove_config.get("final_warning_seconds", 30)) if stove_config else 30
    cooking_time_sec = max(1, cooking_time_minutes) * 60
    final_warning_sec = max(1, min(final_warning_seconds, 300))

    # Get first microwave in same room as stove (for backward compat display)
    microwave_plug_entity = None
    microwave_power_threshold = 50
    if stove_config and stove_plug_entity:
        for room in config_manager.energy_config.get("rooms", []):
            outlets = room.get("outlets", [])
            has_stove = any(o.get("type") == "stove" and o.get("plug1_entity") == stove_plug_entity for o in outlets)
            if has_stove:
                for outlet in outlets:
                    if outlet.get("type") == "microwave" and outlet.get("plug1_entity"):
                        microwave_plug_entity = outlet.get("plug1_entity")
                        microwave_power_threshold = int(outlet.get("microwave_power_threshold", 50))
                        break
                break

    result: dict[str, Any] = {
        "configured": bool(stove_plug_entity and presence_sensor),
        "stove_state": "off",
        "presence_detected": False,
        "current_power": 0.0,
        "timer_phase": "none",
        "time_remaining": 0,
        "cooking_time_minutes": cooking_time_minutes,
        "final_warning_seconds": final_warning_sec,
        "microwave_plug_entity": microwave_plug_entity,
        "microwave_power_threshold": microwave_power_threshold,
    }

    if not result["configured"]:
        connection.send_result(msg["id"], result)
        return

    if stove_plug_entity:
        current_power = _get_power_value(hass, stove_plug_entity)
        result["current_power"] = round(current_power, 1)
        result["stove_state"] = "on" if current_power > stove_power_threshold else "off"

    if presence_sensor:
        presence_state = hass.states.get(presence_sensor)
        state_val = (presence_state.state or "").lower() if presence_state else ""
        result["presence_detected"] = state_val in ("detected", "on")

    key = stove_plug_entity
    if hasattr(energy_monitor, "_stove_timer_phase") and isinstance(energy_monitor._stove_timer_phase, dict):
        result["timer_phase"] = energy_monitor._stove_timer_phase.get(key, "none")
        timer_start = energy_monitor._stove_timer_start.get(key) if isinstance(energy_monitor._stove_timer_start, dict) else None
        timer_phase = result["timer_phase"]
        if timer_start and timer_phase != "none":
            from homeassistant.util import dt as dt_util
            now = dt_util.now()
            elapsed = (now - timer_start).total_seconds()
            if timer_phase == "15min":
                result["time_remaining"] = int(max(0, cooking_time_sec - elapsed))
            elif timer_phase == "30sec":
                result["time_remaining"] = int(max(0, final_warning_sec - elapsed))

    connection.send_result(msg["id"], result)


def _get_power_value(hass: HomeAssistant, entity_id: str) -> float:
    """Get power value from an entity in Watts."""
    state = hass.states.get(entity_id)
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
                return val
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


@websocket_api.websocket_command(
    {
        vol.Required("type"): "smart_dashboards/send_test_notification",
        vol.Required("target_person"): str,
        vol.Required("notification_type"): str,
    }
)
@websocket_api.async_response
async def websocket_send_test_notification(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Send a test notification to a specific person."""
    config_manager = hass.data[DOMAIN].get("config_manager")
    if not config_manager:
        connection.send_error(msg["id"], "not_ready", "Config manager not initialized")
        return

    target_person = msg["target_person"]
    notification_type = msg["notification_type"]

    person_state = hass.states.get(target_person)
    if not person_state:
        connection.send_error(msg["id"], "invalid_person", f"Person entity not found: {target_person}")
        return

    person_name = (
        person_state.attributes.get("friendly_name")
        or target_person.replace("person.", "").replace("_", " ").title()
    )

    tts_settings = config_manager.energy_config.get("tts_settings", {})
    prefix = tts_settings.get("prefix", "Message from Home Energy.")
    notification_title = str(
        tts_settings.get("notification_title") or DEFAULT_NOTIFICATION_TITLE
    ).strip() or DEFAULT_NOTIFICATION_TITLE

    type_map = {
        "budget_hit": ("notify_budget_hit_title", "notify_budget_hit_msg"),
        "enforcement_phase1": ("notify_enforcement_phase1_title", "notify_enforcement_phase1_msg"),
        "enforcement_phase2": ("notify_enforcement_phase2_title", "notify_enforcement_phase2_msg"),
        "ac_auto_off": ("notify_ac_auto_off_title", "notify_ac_auto_off_msg"),
        "ac_auto_on": ("notify_ac_auto_on_title", "notify_ac_auto_on_msg"),
        "manual_toggle": ("notify_manual_toggle_title", "notify_manual_toggle_msg"),
        "heater_auto_on": ("notify_heater_auto_on_title", "notify_heater_auto_on_msg"),
        "heater_auto_off": ("notify_heater_auto_off_title", "notify_heater_auto_off_msg"),
        "vent_auto_on": ("notify_vent_auto_on_title", "notify_vent_auto_on_msg"),
        "vent_auto_off": ("notify_vent_auto_off_title", "notify_vent_auto_off_msg"),
    }

    if notification_type not in type_map:
        connection.send_error(msg["id"], "invalid_type", f"Unknown notification type: {notification_type}")
        return

    title_key, msg_key = type_map[notification_type]

    default_titles = {
        "notify_budget_hit_title": "{notification_title} Budget Exceeded",
        "notify_enforcement_phase1_title": "{notification_title} Enforcement Phase 1",
        "notify_enforcement_phase2_title": "{notification_title} Enforcement Phase 2",
        "notify_ac_auto_off_title": "{notification_title} Air Conditioner Off",
        "notify_ac_auto_on_title": "{notification_title} Air Conditioner On",
        "notify_manual_toggle_title": "{notification_title} Appliance Toggled",
        "notify_heater_auto_on_title": "{notification_title} Heater On",
        "notify_heater_auto_off_title": "{notification_title} Heater Off",
        "notify_vent_auto_on_title": "{notification_title} Vent On",
        "notify_vent_auto_off_title": "{notification_title} Vent Off",
    }
    default_msgs = {
        "notify_budget_hit_msg": "{room_name} has exceeded its daily budget of {kwh_budget} kWh (used {kwh_used} kWh).",
        "notify_enforcement_phase1_msg": "{room_name} has entered enforcement phase 1 (volume escalation). Please reduce power usage.",
        "notify_enforcement_phase2_msg": "{room_name} has entered enforcement phase 2 (power cycling). Please reduce power usage.",
        "notify_ac_auto_off_msg": (
            "{outlet_name} was turned off because {person_name} left the monitored zone."
        ),
        "notify_ac_auto_on_msg": (
            "{outlet_name} was turned back on because {person_name} is nearby."
        ),
        "notify_manual_toggle_msg": "{user_name} turned {action} {outlet_name} in {room_name}.",
        "notify_heater_auto_on_msg": "{room_name} is {temperature}°, turning on {outlet_name}.",
        "notify_heater_auto_off_msg": "{room_name} reached {temperature}°, turning off {outlet_name}.",
        "notify_vent_auto_on_msg": "Motion detected in {room_name}, turning on {outlet_name}.",
        "notify_vent_auto_off_msg": "No motion in {room_name}, turning off {outlet_name}.",
    }

    title_template = tts_settings.get(title_key) or default_titles.get(title_key, "Test Notification")
    msg_template = tts_settings.get(msg_key) or default_msgs.get(msg_key, "This is a test notification.")

    sample_vars = {
        "prefix": prefix,
        "notification_title": notification_title,
        "room_name": "Sample Room",
        "kwh_budget": "5.0",
        "kwh_used": "6.2",
        "outlet_name": "Sample Appliance",
        "user_name": "Test User",
        "action": "on",
        "person_name": person_name,
        "person": person_name,
        "temperature": "62",
        "threshold": "65",
        "comfort": "68",
    }

    try:
        title = title_template.format(**sample_vars)
        message = msg_template.format(**sample_vars)
    except (KeyError, ValueError) as e:
        _LOGGER.warning("Failed to format test notification template: %s", e)
        title = f"{notification_title} Test Notification"
        message = "This is a test notification from Smart Dashboards."

    result = await async_send_notify_push(hass, target_person, title, message)
    if result.ok:
        connection.send_result(
            msg["id"],
            {"success": True, "target": result.target},
        )
        return

    if result.error and "No mobile_app notify target" in result.error:
        connection.send_error(
            msg["id"],
            "no_notify_target",
            "Could not find a notify target for this person. Link a phone under "
            "Settings → People (device must appear under the person), and ensure the "
            "Home Assistant Companion app is logged in.",
        )
        return
    if result.error and "Unknown notify target mode" in result.error:
        connection.send_error(msg["id"], "unknown_mode", result.error)
        return

    connection.send_error(
        msg["id"],
        "send_failed",
        result.error or "Failed to send notification.",
    )


@websocket_api.websocket_command(
    {vol.Required("type"): "smart_dashboards/clear_statistics_cache"}
)
@websocket_api.async_response
async def websocket_clear_statistics_cache(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Clear statistics and kWh history caches to force fresh recalculation."""
    _clear_recorder_derived_caches()
    config_manager = hass.data[DOMAIN].get("config_manager")
    if config_manager:
        await config_manager.async_save_statistics_cache({})
    connection.send_result(msg["id"], {"success": True})


@websocket_api.websocket_command(
    {vol.Required("type"): "smart_dashboards/hard_refresh_statistics"}
)
async def websocket_hard_refresh_statistics(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Hard refresh statistics with progress streaming to ALL connected clients.

    Fires progress events to the event bus so all subscribed clients see the modal
    and progress in real-time, not just the client that initiated the refresh.
    """
    msg_id = msg["id"]

    def send_progress(step: str, progress: int, log: str, **extra) -> None:
        """Fire progress event to bus for broadcast to all clients."""
        hass.bus.async_fire(
            "smart_dashboards_hard_refresh_progress",
            {"step": step, "progress": progress, "log": log, **extra},
        )

    config_manager = hass.data[DOMAIN].get("config_manager")
    if not config_manager:
        connection.send_error(msg_id, "not_ready", "Config manager not initialized")
        return

    # Acknowledge the command immediately
    connection.send_result(msg_id, {"success": True})

    # Build room name lookup for detailed logging
    room_names: dict[str, str] = {}
    for room in config_manager.energy_config.get("rooms", []):
        rid = room.get("id", room["name"].lower().replace(" ", "_"))
        room_names[rid] = room.get("name", rid)

    try:
        # Fire "started" event so ALL clients show the modal
        send_progress("initializing", 0, "Hard refresh started...", started=True)

        # Step 1: Clear caches
        send_progress("clear_cache", 5, "Clearing statistics caches...")
        _clear_recorder_derived_caches()
        await config_manager.async_save_statistics_cache({})
        send_progress("clear_cache", 10, "Caches cleared")

        # Step 2: Get date range
        send_progress("date_range", 12, "Determining billing date range...")
        billing_a, billing_b = config_manager.get_billing_date_range()
        start, end, _ = config_manager.get_statistics_date_range(
            date_start=None, date_end=None
        )
        if not start or not end:
            today = dt_util.now().strftime("%Y-%m-%d")
            start = (dt_util.now() - timedelta(days=30)).strftime("%Y-%m-%d")
            end = today
        send_progress("date_range", 15, f"Date range: {start} to {end}")

        # Step 3: Collect energy sources
        send_progress("collect_sources", 18, "Collecting energy sources from config...")
        entity_to_room, switch_specs = _collect_statistics_energy_sources(config_manager)
        num_entities = len(entity_to_room)
        num_switches = len(switch_specs)
        send_progress(
            "collect_sources",
            20,
            f"Found {num_entities} power sensors, {num_switches} switch specs",
        )

        # Step 4: Query recorder history
        send_progress("recorder_query", 22, "Querying recorder history (this may take a while)...")

        try:
            start_dt = dt_util.parse_datetime(f"{start} 00:00:00")
            end_dt = dt_util.parse_datetime(f"{end} 23:59:59")
            if start_dt and end_dt:
                start_dt = dt_util.as_utc(start_dt)
                end_dt = dt_util.as_utc(end_dt)
                now_utc = dt_util.utcnow()
                end_dt = min(end_dt, now_utc)
        except (ValueError, TypeError):
            start_dt = None
            end_dt = None

        recorder_wh = 0.0
        recorder_days: set[str] = set()
        all_expected_days: set[str] = set()
        room_day_wh: dict[str, dict[str, float]] = {}

        if start_dt and end_dt and (entity_to_room or switch_specs):
            # Query each entity and track progress with per-appliance logging
            total_sources = num_entities + num_switches
            completed = 0

            sem = asyncio.Semaphore(_STATISTICS_QUERY_CONCURRENCY)

            async def query_entity(eid: str, room_id: str) -> tuple[str, str, float, dict[str, float]]:
                async with sem:
                    wh, by_day, _meta = await hass.async_add_executor_job(
                        _sync_compute_plug_wh_total_and_by_day,
                        hass,
                        eid,
                        start_dt,
                        end_dt,
                    )
                return eid, room_id, float(wh), by_day

            async def query_switch(spec: dict[str, Any]) -> tuple[str, str, float, dict[str, float]]:
                async with sem:
                    wh, by_day = await hass.async_add_executor_job(
                        _sync_integrate_switch_constant_wh_total_and_by_day,
                        hass,
                        spec["switch_entity"],
                        float(spec["watts"]),
                        start_dt,
                        end_dt,
                    )
                return spec["switch_entity"], spec["room_id"], float(wh), by_day

            # Run queries in batches for progress updates
            all_coros = []
            all_coros.extend(query_entity(eid, rid) for eid, rid in entity_to_room.items())
            all_coros.extend(query_switch(s) for s in switch_specs)

            send_progress("appliance_calc", 22, "Calculating appliance usage...")

            for i, coro in enumerate(all_coros):
                try:
                    source_id, room_id, wh, by_day = await coro
                    recorder_wh += wh
                    recorder_days.update(by_day.keys())
                    rmap = room_day_wh.setdefault(room_id, {})
                    for dkey, dwh in by_day.items():
                        rmap[dkey] = rmap.get(dkey, 0.0) + float(dwh)

                    # Log each appliance calculation
                    room_name = room_names.get(room_id, room_id)
                    kwh = wh / 1000.0
                    send_progress(
                        "appliance_calc",
                        22 + int(((i + 1) / total_sources) * 38),  # 22% to 60%
                        f"  {source_id}: {kwh:.3f} kWh → {room_name}",
                    )
                except Exception as err:
                    _LOGGER.warning("Hard refresh: error querying source: %s", err)
                    send_progress(
                        "appliance_calc",
                        22 + int(((i + 1) / total_sources) * 38),
                        f"  Error: {err}",
                    )

                completed += 1

            send_progress(
                "appliance_calc",
                60,
                f"Appliances done: {recorder_wh/1000:.2f} kWh from {completed} sources",
            )

            # Step 5: LTS fallback for missing days
            cur = start_dt
            while cur <= end_dt:
                all_expected_days.add(cur.strftime("%Y-%m-%d"))
                cur += timedelta(days=1)

            missing_days = all_expected_days - recorder_days

            if missing_days and entity_to_room:
                send_progress(
                    "lts_fallback",
                    62,
                    f"LTS fallback: {len(missing_days)} days missing, querying Long-Term Statistics...",
                )

                lts_result = await hass.async_add_executor_job(
                    _sync_fetch_lts_wh_by_day,
                    hass,
                    list(entity_to_room.keys()),
                    start_dt,
                    end_dt,
                )

                lts_wh_added = 0.0
                lts_days_filled: set[str] = set()
                for eid, lts_day_wh in lts_result.items():
                    room_id = entity_to_room.get(eid)
                    if not room_id:
                        continue
                    rmap = room_day_wh.setdefault(room_id, {})
                    for day_key, wh in lts_day_wh.items():
                        if day_key in missing_days and rmap.get(day_key, 0.0) == 0.0:
                            rmap[day_key] = rmap.get(day_key, 0.0) + wh
                            lts_wh_added += wh
                            lts_days_filled.add(day_key)

                send_progress(
                    "lts_fallback",
                    68,
                    f"LTS added {lts_wh_added/1000:.2f} kWh for {len(lts_days_filled)} days",
                )
            else:
                send_progress("lts_fallback", 68, "No LTS fallback needed (all days have data)")

            # Step 6: Room summaries
            send_progress("room_summary", 70, "Room summaries:")
            for rid, day_map in room_day_wh.items():
                room_total_kwh = sum(day_map.values()) / 1000.0
                room_name = room_names.get(rid, rid)
                send_progress("room_summary", 72, f"  {room_name}: {room_total_kwh:.2f} kWh")

            # Whole home total
            whole_home_wh = sum(sum(d.values()) for d in room_day_wh.values())
            whole_home_kwh = whole_home_wh / 1000.0
            send_progress("whole_home", 75, f"Whole home (recorder): {whole_home_kwh:.2f} kWh")

        else:
            if not (start_dt and end_dt):
                send_progress(
                    "recorder_query",
                    35,
                    "Skipping appliance recorder queries (invalid or missing billing date range).",
                )
            elif not entity_to_room and not switch_specs:
                send_progress(
                    "recorder_query",
                    35,
                    "No energy sources configured for statistics (no room power sensors or switch loads).",
                )
            else:
                send_progress(
                    "recorder_query",
                    35,
                    "Skipping per-appliance recorder pass.",
                )

        # Step 7: Build full statistics payload
        send_progress("build_payload", 78, "Building statistics payload...")
        result = await async_build_statistics_payload(
            hass, config_manager, date_start=None, date_end=None
        )
        send_progress("build_payload", 85, f"Payload built: {result.get('total_kwh', 0):.2f} kWh total")

        # Step 8: Build billing daily history
        send_progress("daily_history", 88, "Building daily billing history...")
        try:
            daily_history = await async_build_billing_daily_history_from_recorder(
                hass, config_manager, start, end
            )
            result["daily_history"] = daily_history
            result["daily_history_range"] = {"date_start": start, "date_end": end}
            send_progress("daily_history", 92, "Daily history built")
        except Exception as err:
            _LOGGER.warning("Hard refresh: daily_history failed: %s", err)
            send_progress("daily_history", 92, f"Daily history warning: {err}")

        # Step 9: Save to JSON cache
        send_progress("save_cache", 95, "Saving to statistics cache...")
        to_save = dict(result)
        to_save.pop("statistics_pending", None)
        await config_manager.async_save_statistics_cache(to_save)
        send_progress("save_cache", 98, "Cache saved")

        # Step 10: Fire event for live UI push (statistics data)
        hass.bus.async_fire("smart_dashboards_statistics_updated", {"data": to_save})

        # Send final complete event (broadcast to all clients)
        send_progress(
            "complete",
            100,
            "Hard refresh complete!",
            complete=True,
            success=True,
            total_kwh=result.get("total_kwh", 0),
            date_start=start,
            date_end=end,
            recorder_days=len(recorder_days),
            total_days=len(all_expected_days),
        )

    except Exception as err:
        _LOGGER.exception("Hard refresh failed: %s", err)
        send_progress(
            "error",
            0,
            f"Error: {err}",
            complete=True,
            success=False,
            error=str(err),
        )


@websocket_api.websocket_command(
    {vol.Required("type"): "smart_dashboards/get_statistics_sources"}
)
@websocket_api.async_response
async def websocket_get_statistics_sources(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return which entities contribute to each room's statistics for debugging."""
    config_manager = hass.data[DOMAIN].get("config_manager")
    if not config_manager:
        connection.send_error(msg["id"], "not_ready", "Config manager not initialized")
        return

    entity_to_room, switch_specs = _collect_statistics_energy_sources(config_manager)

    power_sensors = []
    for entity_id, room_id in entity_to_room.items():
        state = hass.states.get(entity_id)
        power_sensors.append({
            "entity_id": entity_id,
            "room_id": room_id,
            "state": state.state if state else None,
            "unit": state.attributes.get("unit_of_measurement") if state else None,
        })

    switch_sources = []
    for spec in switch_specs:
        state = hass.states.get(spec["switch_entity"])
        switch_sources.append({
            "switch_entity": spec["switch_entity"],
            "room_id": spec["room_id"],
            "watts": spec["watts"],
            "state": state.state if state else None,
        })

    connection.send_result(msg["id"], {
        "power_sensors": power_sensors,
        "switch_sources": switch_sources,
    })


@websocket_api.websocket_command(
    {
        vol.Required("type"): "smart_dashboards/get_statistics_source_breakdown",
        vol.Optional("date_start"): str,
        vol.Optional("date_end"): str,
    }
)
@websocket_api.async_response
async def websocket_get_statistics_source_breakdown(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Per-entity Wh/kWh and aggregation method for the statistics date range."""
    config_manager = hass.data[DOMAIN].get("config_manager")
    if not config_manager:
        connection.send_error(msg["id"], "not_ready", "Config manager not initialized")
        return

    ds = (msg.get("date_start") or "").strip() or None
    de = (msg.get("date_end") or "").strip() or None
    start, end, _ = config_manager.get_statistics_date_range(
        date_start=ds, date_end=de
    )
    if not start or not end:
        today = dt_util.now().strftime("%Y-%m-%d")
        start = (dt_util.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        end = today

    try:
        _tw, _rw, _rd, breakdown = await _compute_kwh_from_history(
            hass,
            config_manager,
            start,
            end,
            return_breakdown=True,
        )
    except Exception as err:
        _LOGGER.warning("Statistics source breakdown failed: %s", err)
        connection.send_error(msg["id"], "stats_failed", str(err))
        return

    connection.send_result(
        msg["id"],
        {
            "date_start": start,
            "date_end": end,
            "sources": breakdown or [],
        },
    )


@websocket_api.websocket_command(
    {vol.Required("type"): "smart_dashboards/get_zone_health_status"}
)
@websocket_api.async_response
async def websocket_get_zone_health_status(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return zone health tracking status for all configured persons."""
    energy_monitor = hass.data[DOMAIN].get("energy_monitor")
    if not energy_monitor:
        connection.send_error(msg["id"], "not_ready", "Energy monitor not initialized")
        return
    status = energy_monitor.get_zone_health_status()
    connection.send_result(msg["id"], status)


@websocket_api.websocket_command(
    {vol.Required("type"): "smart_dashboards/refresh_zone_health"}
)
@websocket_api.async_response
async def websocket_refresh_zone_health(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Force recorder refresh for all persons + device_trackers and re-run zone health logic."""
    energy_monitor = hass.data[DOMAIN].get("energy_monitor")
    if not energy_monitor:
        connection.send_error(msg["id"], "not_ready", "Energy monitor not initialized")
        return
    status = await energy_monitor.async_force_zone_health_refresh()
    connection.send_result(msg["id"], status)


@websocket_api.websocket_command(
    {vol.Required("type"): "smart_dashboards/get_room_ratings"}
)
@websocket_api.async_response
async def websocket_get_room_ratings(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Recompute room ratings without persisting; refresh shared cache on success."""
    config_manager = hass.data.get(DOMAIN, {}).get("config_manager")
    if not config_manager:
        connection.send_error(msg["id"], "not_ready", "Config manager not initialized")
        return

    domain_data = hass.data.setdefault(DOMAIN, {})

    def _recompute_and_payload() -> dict[str, Any]:
        full = recompute_room_ratings(hass, config_manager, persist=False)
        return ratings_payload_for_ws(full)

    try:
        payload = await hass.async_add_executor_job(_recompute_and_payload)
        domain_data["room_ratings_cache"] = payload
    except Exception:
        _LOGGER.exception("smart_dashboards/get_room_ratings recompute failed")
        cached = domain_data.get("room_ratings_cache")
        if isinstance(cached, dict) and isinstance(cached.get("rooms"), dict):
            payload = cached
        else:

            def _load_file_payload() -> dict[str, Any]:
                return ratings_payload_for_ws(load_ratings(ratings_store_path(hass)))

            try:
                payload = await hass.async_add_executor_job(_load_file_payload)
            except Exception:
                _LOGGER.exception("get_room_ratings fallback file load failed")
                payload = ratings_payload_for_ws({"rooms": {}})

    connection.send_result(msg["id"], payload)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "smart_dashboards/send_efficiency_digest_test",
        vol.Required("target_person"): str,
        vol.Optional("room_id"): str,
    }
)
@websocket_api.async_response
async def websocket_send_efficiency_digest_test(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Send a sample efficiency digest notification (same templates as daily digest)."""
    ok, err = await async_send_efficiency_digest_test(
        hass,
        msg["target_person"],
        msg.get("room_id"),
    )
    if ok:
        connection.send_result(msg["id"], {"success": True})
        return
    connection.send_error(
        msg["id"],
        "efficiency_digest_test_failed",
        err or "Failed to send efficiency digest test.",
    )


@websocket_api.websocket_command(
    {vol.Required("type"): "smart_dashboards/dashboard_heartbeat"}
)
@websocket_api.async_response
async def websocket_dashboard_heartbeat(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Record a dashboard visit for engagement scoring (throttled server-side)."""
    path = ratings_store_path(hass)
    user_key = _dashboard_ws_user_key(connection)
    config_manager = hass.data.get(DOMAIN, {}).get("config_manager")

    def _beat() -> None:
        data = load_ratings(path)
        cap = None
        if config_manager is not None:
            cap = int(
                efficiency_scoring_params_from_manager(config_manager)[
                    "engagement_max_visits_per_hour"
                ]
            )
        record_dashboard_heartbeat(data, user_key, max_per_hour=cap)
        save_ratings(path, data)

    await hass.async_add_executor_job(_beat)
    connection.send_result(msg["id"], {"success": True})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "smart_dashboards/get_light_automations",
        vol.Required("room_id"): str,
    }
)
@websocket_api.async_response
async def websocket_get_light_automations(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Get light automation config for a room."""
    config_manager = hass.data[DOMAIN].get("config_manager")
    if not config_manager:
        connection.send_error(msg["id"], "not_ready", "Config manager not initialized")
        return

    room_id = msg["room_id"]
    automations = await hass.async_add_executor_job(
        config_manager.get_light_automations, room_id
    )
    connection.send_result(msg["id"], automations)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "smart_dashboards/save_light_automations",
        vol.Required("room_id"): str,
        vol.Required("automations"): dict,
    }
)
@websocket_api.async_response
async def websocket_save_light_automations(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Save light automation config for a room."""
    config_manager = hass.data[DOMAIN].get("config_manager")
    if not config_manager:
        connection.send_error(msg["id"], "not_ready", "Config manager not initialized")
        return

    room_id = msg["room_id"]
    automations = msg["automations"]

    try:
        await hass.async_add_executor_job(
            config_manager.save_light_automations, room_id, automations
        )
        connection.send_result(msg["id"], {"success": True})
    except Exception as e:
        _LOGGER.error("Failed to save light automations for room %s: %s", room_id, e)
        connection.send_error(msg["id"], "save_failed", str(e))


@websocket_api.websocket_command(
    {
        vol.Required("type"): "smart_dashboards/test_tuya_scene",
        vol.Required("entity_id"): str,
        vol.Required("scene_data"): dict,
    }
)
@websocket_api.async_response
async def websocket_test_tuya_scene(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Test a Tuya scene on a light (immediate preview)."""
    import json
    import time

    entity_id = msg["entity_id"]
    scene_data = msg["scene_data"]

    if not entity_id.startswith("light."):
        connection.send_error(msg["id"], "invalid_entity", "Entity must be a light")
        return

    try:
        scene_hex = scene_data.get("scene_data_v2", "")
        if not scene_hex:
            connection.send_error(msg["id"], "invalid_scene", "No scene_data_v2 hex string")
            return

        pause_seconds = scene_data.get("pause_enforcement", 30)
        energy_monitor = hass.data.get("smart_dashboards", {}).get("energy_monitor")
        if energy_monitor:
            energy_monitor.pause_light_enforcement(pause_seconds)

        if hass.services.has_service("tuya_local", "set_dp"):
            await hass.services.async_call(
                "tuya_local",
                "set_dp",
                {
                    "entity_id": entity_id,
                    "dp": 25,
                    "value": scene_hex,
                },
            )
        else:
            await hass.services.async_call(
                "light",
                "turn_on",
                {
                    "entity_id": entity_id,
                    "effect": "scene",
                },
            )
        connection.send_result(msg["id"], {"success": True})
    except Exception as e:
        _LOGGER.error("Failed to test Tuya scene on %s: %s", entity_id, e)
        connection.send_error(msg["id"], "scene_test_failed", str(e))
