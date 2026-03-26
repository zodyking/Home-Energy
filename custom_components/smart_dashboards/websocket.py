"""WebSocket API for Smart Dashboards."""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import date, datetime, timedelta
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from .config_manager import vent_like_energy_tracking_key
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


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


# Server-side cache for get_statistics to avoid heavy recorder queries
# Short TTL while range includes "today" (live); longer TTL for past-only ranges
_STATISTICS_CACHE: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}
_STATISTICS_CACHE_TTL_LIVE = 60.0
_STATISTICS_CACHE_TTL_PAST = 3600.0
_STATISTICS_QUERY_CONCURRENCY = 6
# Throttle background cache priming vs. statistics_refresh_seconds
_last_stats_prime_at: float = 0.0


async def _async_register_statistics_cache_primer(hass: HomeAssistant) -> None:
    """Periodic background prime of default-range statistics cache."""

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
    websocket_api.async_register_command(hass, websocket_get_entities_by_area)
    websocket_api.async_register_command(hass, websocket_get_areas)
    websocket_api.async_register_command(hass, websocket_get_switches)
    websocket_api.async_register_command(hass, websocket_verify_passcode)
    websocket_api.async_register_command(hass, websocket_toggle_switch)
    websocket_api.async_register_command(hass, websocket_get_breaker_data)
    websocket_api.async_register_command(hass, websocket_test_trip_breaker)
    websocket_api.async_register_command(hass, websocket_get_stove_data)
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
        connection.send_result(msg["id"], {"success": True})
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
    energy_monitor = hass.data.get(DOMAIN, {}).get("energy_monitor")
    result: dict[str, Any] = {
        "rooms": [],
        "total_warnings": event_counts.get("total_warnings", 0),
        "total_shutoffs": event_counts.get("total_shutoffs", 0),
        "total_power_cycles": event_counts.get("total_power_cycles", 0),
    }

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
                # Vent / wall heater: switch on + static watts or power sensor
                switch_entity = outlet.get("switch_entity")
                watts_when_on = float(outlet.get("watts_when_on", 0) or 0)
                power_ent = (
                    outlet.get("power_sensor_entity")
                    if outlet.get("power_source") == "sensor"
                    else None
                )
                if switch_entity:
                    state = hass.states.get(switch_entity)
                    is_on = bool(state and (state.state or "off").lower() in ("on",))
                    if power_ent:
                        watts = _get_power_value(hass, power_ent) if is_on else 0.0
                        day_wh = config_manager.get_day_energy(power_ent)
                    else:
                        watts = watts_when_on if is_on else 0.0
                        tracking_key = vent_like_energy_tracking_key(room_id, outlet)
                        day_wh = config_manager.get_day_energy(tracking_key)
                else:
                    watts = 0.0
                    if power_ent:
                        day_wh = config_manager.get_day_energy(power_ent)
                    else:
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
        result["rooms"].append(room_data)

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
        result = config_manager.get_daily_history_for_range(date_start, date_end)
    else:
        days = min(45, max(1, msg.get("days", 30)))
        result = config_manager.get_daily_history(days=days)
    connection.send_result(msg["id"], result)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "smart_dashboards/get_intraday_history",
        vol.Optional("room_id"): str,
        vol.Optional("minutes"): vol.Coerce(int),
    }
)
@websocket_api.async_response
async def websocket_get_intraday_history(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Get minute-by-minute power history for 24-hour charts."""
    config_manager = hass.data[DOMAIN].get("config_manager")
    if not config_manager:
        connection.send_error(msg["id"], "not_ready", "Config manager not initialized")
        return
    
    room_id = msg.get("room_id")
    minutes = min(1440, max(1, msg.get("minutes", 1440)))  # Max 24 hours
    
    if room_id:
        # Get room-specific intraday history
        data = config_manager.get_room_intraday_history(room_id, minutes)
    else:
        # Get total intraday history (all rooms)
        data = config_manager.get_total_intraday_history(minutes)
    
    # Ensure at least one data point (current power if no history)
    if not data["timestamps"]:
        from homeassistant.util import dt as dt_util
        now = dt_util.now().strftime("%Y-%m-%d %H:%M")

        def _get_power(entity_id: str) -> float:
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
                                current_watts += _get_power(power_ent)
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
                                current_watts += _get_power(power_ent)
                            elif watts_when_on > 0:
                                current_watts += watts_when_on
                else:
                    for eid in (outlet.get("plug1_entity"), outlet.get("plug2_entity")):
                        if eid:
                            current_watts += _get_power(eid)
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


def _integrate_power_to_wh_clipped(states: list, start_dt, end_dt) -> float:
    """Integrate power (W) to Wh using trapezoids between states, clipped to [start_dt, end_dt]."""
    if not states:
        return 0.0
    states = sorted(states, key=lambda s: s.last_updated)
    total_wh = 0.0

    def w_at(s):
        return _parse_power_from_state_object(s)

    t_first = states[0].last_updated
    if t_first > start_dt:
        w0 = w_at(states[0])
        seg_end = min(t_first, end_dt)
        if seg_end > start_dt:
            total_wh += w0 * (seg_end - start_dt).total_seconds() / 3600.0

    for i in range(len(states) - 1):
        s1, s2 = states[i], states[i + 1]
        a, b = s1.last_updated, s2.last_updated
        if b <= a:
            continue
        w1, w2 = w_at(s1), w_at(s2)
        overlap_start = max(a, start_dt)
        overlap_end = min(b, end_dt)
        if overlap_end <= overlap_start:
            continue
        dur = (b - a).total_seconds()
        if dur <= 0:
            continue

        def w_linear(t):
            frac = (t - a).total_seconds() / dur
            return w1 + (w2 - w1) * frac

        wa = w_linear(overlap_start)
        wb = w_linear(overlap_end)
        dt_sec = (overlap_end - overlap_start).total_seconds()
        total_wh += (wa + wb) / 2.0 * (dt_sec / 3600.0)

    t_last = states[-1].last_updated
    if t_last < end_dt:
        wn = w_at(states[-1])
        overlap_start = max(t_last, start_dt)
        overlap_end = end_dt
        if overlap_end > overlap_start:
            total_wh += wn * (overlap_end - overlap_start).total_seconds() / 3600.0

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


def _trap_wh_linear(
    w1: float, w2: float, ta: datetime, tb: datetime, t0: datetime, t1: datetime
) -> float:
    """Trapezoid Wh for linear w from (ta,w1) to (tb,w2) on [t0,t1] subset of [ta,tb]."""
    if t1 <= t0 or tb <= ta:
        return 0.0
    dur = (tb - ta).total_seconds()
    if dur <= 0:
        return 0.0

    def w_at(t: datetime) -> float:
        frac = (t - ta).total_seconds() / dur
        return w1 + (w2 - w1) * frac

    wa = w_at(t0)
    wb = w_at(t1)
    return (wa + wb) / 2.0 * ((t1 - t0).total_seconds() / 3600.0)


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
    """Same physics as _integrate_power_to_wh_clipped; Wh split by local calendar day."""
    buckets: dict[str, float] = {}
    if not states:
        return buckets
    states = sorted(states, key=lambda s: s.last_updated)

    def w_at(s):
        return _parse_power_from_state_object(s)

    t_first = states[0].last_updated
    if t_first > start_dt:
        w0 = w_at(states[0])
        seg_end = min(t_first, end_dt)
        if seg_end > start_dt:
            _add_constant_wh_to_date_buckets(buckets, w0, start_dt, seg_end)

    for i in range(len(states) - 1):
        s1, s2 = states[i], states[i + 1]
        a, b = s1.last_updated, s2.last_updated
        if b <= a:
            continue
        w1, w2 = w_at(s1), w_at(s2)
        overlap_start = max(a, start_dt)
        overlap_end = min(b, end_dt)
        if overlap_end <= overlap_start:
            continue
        for cs, ce, day_key in _iter_local_calendar_chunks(overlap_start, overlap_end):
            wh = _trap_wh_linear(w1, w2, a, b, cs, ce)
            buckets[day_key] = buckets.get(day_key, 0.0) + wh

    t_last = states[-1].last_updated
    if t_last < end_dt:
        wn = w_at(states[-1])
        overlap_start = max(t_last, start_dt)
        overlap_end = end_dt
        if overlap_end > overlap_start:
            _add_constant_wh_to_date_buckets(buckets, wn, overlap_start, overlap_end)

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
                for eid in (outlet.get("plug1_entity"), outlet.get("plug2_entity")):
                    if eid and isinstance(eid, str) and eid.strip():
                        entity_to_room[eid.strip()] = room_id

    return entity_to_room, switch_specs


def _sync_integrate_entity_wh(
    hass: HomeAssistant,
    entity_id: str,
    start_dt,
    end_dt,
) -> float:
    """Load one entity's history and integrate W -> Wh."""
    total, _by = _sync_integrate_entity_wh_total_and_by_day(
        hass, entity_id, start_dt, end_dt
    )
    return total


def _sync_integrate_entity_wh_total_and_by_day(
    hass: HomeAssistant,
    entity_id: str,
    start_dt,
    end_dt,
) -> tuple[float, dict[str, float]]:
    """Integrate W -> Wh for full range and per local calendar day (same recorder fetch)."""
    from homeassistant.components.recorder.history import get_significant_states_with_session
    from homeassistant.components.recorder.util import session_scope

    with session_scope(hass=hass, read_only=True) as session:
        states_dict = get_significant_states_with_session(
            hass,
            session,
            start_dt,
            end_dt,
            [entity_id],
            None,
            include_start_time_state=True,
            significant_changes_only=True,
            minimal_response=False,
            no_attributes=False,
        )
    states = states_dict.get(entity_id) or []
    total = _integrate_power_to_wh_clipped(states, start_dt, end_dt)
    by_day = _integrate_power_to_wh_by_local_date(states, start_dt, end_dt)
    return total, by_day


def _sync_integrate_switch_constant_wh(
    hass: HomeAssistant,
    switch_entity: str,
    watts: float,
    start_dt,
    end_dt,
) -> float:
    total, _by = _sync_integrate_switch_constant_wh_total_and_by_day(
        hass, switch_entity, watts, start_dt, end_dt
    )
    return total


def _sync_integrate_switch_constant_wh_total_and_by_day(
    hass: HomeAssistant,
    switch_entity: str,
    watts: float,
    start_dt,
    end_dt,
) -> tuple[float, dict[str, float]]:
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
    total = _integrate_switch_constant_wh(states, start_dt, end_dt, watts)
    by_day = _integrate_switch_constant_wh_by_local_date(
        states, start_dt, end_dt, watts
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


async def _compute_kwh_from_history(
    hass: HomeAssistant,
    config_manager,
    start_date: str,
    end_date: str,
) -> tuple[float, dict[str, float], dict[str, dict[str, float]]]:
    """Compute kWh from HA recorder history over start_date..end_date (monitored loads).
    Returns (total_wh, room_wh_map, room_day_wh_map) with room_day_wh_map[room_id][YYYY-MM-DD] = Wh."""
    from homeassistant.util import dt as dt_util

    entity_to_room, switch_specs = _collect_statistics_energy_sources(config_manager)

    try:
        start_dt = dt_util.parse_datetime(f"{start_date} 00:00:00")
        end_dt = dt_util.parse_datetime(f"{end_date} 23:59:59")
        if start_dt is None or end_dt is None:
            return 0.0, {}, {}
        start_dt = dt_util.as_utc(start_dt)
        end_dt = dt_util.as_utc(end_dt)
    except (ValueError, TypeError):
        return 0.0, {}, {}

    now_utc = dt_util.utcnow()
    if start_dt > now_utc:
        return 0.0, {}, {}
    end_dt = min(end_dt, now_utc)
    if end_dt < start_dt:
        return 0.0, {}, {}

    if not entity_to_room and not switch_specs:
        return 0.0, {}, {}

    sem = asyncio.Semaphore(_STATISTICS_QUERY_CONCURRENCY)

    async def one_plug(eid: str, room_id: str) -> tuple[str, float, dict[str, float]]:
        async with sem:
            wh, by_day = await hass.async_add_executor_job(
                _sync_integrate_entity_wh_total_and_by_day,
                hass,
                eid,
                start_dt,
                end_dt,
            )
        return room_id, float(wh), by_day

    async def one_switch(spec: dict[str, Any]) -> tuple[str, float, dict[str, float]]:
        async with sem:
            wh, by_day = await hass.async_add_executor_job(
                _sync_integrate_switch_constant_wh_total_and_by_day,
                hass,
                spec["switch_entity"],
                float(spec["watts"]),
                start_dt,
                end_dt,
            )
        return spec["room_id"], float(wh), by_day

    coros: list = [one_plug(eid, rid) for eid, rid in entity_to_room.items()]
    coros.extend(one_switch(s) for s in switch_specs)
    if not coros:
        return 0.0, {}, {}

    results = await asyncio.gather(*coros)
    room_wh: dict[str, float] = {}
    room_day_wh: dict[str, dict[str, float]] = {}
    total_wh = 0.0
    for room_id, wh, by_day in results:
        total_wh += wh
        room_wh[room_id] = room_wh.get(room_id, 0.0) + wh
        rmap = room_day_wh.setdefault(room_id, {})
        for dkey, dwh in by_day.items():
            rmap[dkey] = rmap.get(dkey, 0.0) + float(dwh)

    return total_wh, room_wh, room_day_wh


async def async_build_statistics_payload(
    hass: HomeAssistant,
    config_manager,
    *,
    date_start: str | None,
    date_end: str | None,
) -> dict[str, Any]:
    """Build statistics payload (shared by WebSocket and background cache priming)."""
    ds = (date_start or "").strip() or None
    de = (date_end or "").strip() or None
    start, end, is_narrowed = config_manager.get_statistics_date_range(
        date_start=ds, date_end=de
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
        "sensor_meta": {"supplier_last_updated": None},
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
            continue
        state = hass.states.get(ent)
        if state is None:
            continue
        lc = state.last_changed
        if lc:
            if key == "current_usage":
                usage_last_changed = lc
            elif key in ("projected_usage", "kwh_cost"):
                if fallback_last_changed is None or lc > fallback_last_changed:
                    fallback_last_changed = lc
        if state.state not in ("unknown", "unavailable", ""):
            try:
                val = str(state.state).strip()
                if key == "kwh_cost":
                    val = val.replace("$", "").replace(",", "").strip()
                result["sensor_values"][key] = float(val)
            except (ValueError, TypeError):
                pass
    supplier_meta_ts = usage_last_changed or fallback_last_changed
    if supplier_meta_ts is not None:
        result["sensor_meta"]["supplier_last_updated"] = dt_util.as_local(
            supplier_meta_ts
        ).isoformat()

    if not start or not end:
        return result

    today = dt_util.now().strftime("%Y-%m-%d")

    try:
        total_wh, room_wh_map, room_day_wh_map = await _compute_kwh_from_history(
            hass, config_manager, start, end
        )
    except Exception as err:  # recorder not ready or history unavailable
        _LOGGER.warning("Statistics kWh from history failed: %s", err)
        total_wh = 0.0
        room_wh_map = {}
        room_day_wh_map = {}
    total_kwh = total_wh / 1000.0 if total_wh else 0.0
    if start <= today:
        effective_end = min(end, today)
        stat_day_keys = (
            _enumerate_date_range_iso(start, effective_end)
            if effective_end >= start
            else []
        )
    else:
        stat_day_keys = []
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

    daily_totals = config_manager.daily_totals
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

    return result


async def _prime_statistics_cache(hass: HomeAssistant) -> None:
    """Fill _STATISTICS_CACHE for the default statistics date range (same as WS without dates)."""
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
    cache_key = (start, end)
    now = time.monotonic()
    _STATISTICS_CACHE[cache_key] = (now, result)


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
    """Get aggregated statistics for a date range."""
    config_manager = hass.data[DOMAIN].get("config_manager")
    if not config_manager:
        connection.send_error(msg["id"], "not_ready", "Config manager not initialized")
        return

    date_start = (msg.get("date_start") or "").strip() or None
    date_end = (msg.get("date_end") or "").strip() or None
    start, end, _is_narrowed = config_manager.get_statistics_date_range(
        date_start=date_start, date_end=date_end
    )
    billing_a, billing_b = config_manager.get_billing_date_range()
    period_source = "billing" if (billing_a and billing_b) else "rolling"

    cache_key = (start or "", end or "")
    now = time.monotonic()
    cache_ttl = _statistics_cache_ttl_seconds(end or "", config_manager)
    if cache_key[0] and cache_key[1]:
        entry = _STATISTICS_CACHE.get(cache_key)
        if entry:
            cached_at, cached_result = entry
            if now - cached_at < cache_ttl:
                connection.send_result(
                    msg["id"], {**cached_result, "period_source": period_source}
                )
                return

    result = await async_build_statistics_payload(
        hass, config_manager, date_start=date_start, date_end=date_end
    )
    start_r = result.get("date_start") or ""
    end_r = result.get("date_end") or ""
    if not start_r or not end_r:
        connection.send_result(msg["id"], result)
        return

    cache_key2 = (start_r, end_r)
    if cache_key2[0] and cache_key2[1]:
        _STATISTICS_CACHE[cache_key2] = (time.monotonic(), result)

    connection.send_result(msg["id"], result)


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
        vol.Required("type"): "smart_dashboards/toggle_switch",
        vol.Required("entity_id"): str,
    }
)
@websocket_api.async_response
async def websocket_toggle_switch(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Toggle a switch entity for testing."""
    entity_id = msg["entity_id"]
    
    if not entity_id or not entity_id.startswith("switch."):
        connection.send_error(msg["id"], "invalid_entity", "Not a valid switch entity")
        return
    
    state = hass.states.get(entity_id)
    if state is None:
        connection.send_error(msg["id"], "entity_not_found", f"Switch {entity_id} not found")
        return
    
    # Toggle the switch
    current_state = state.state
    new_state = "off" if current_state == "on" else "on"
    
    try:
        await hass.services.async_call(
            "switch",
            f"turn_{new_state}",
            {"entity_id": entity_id},
            blocking=True,
        )
        connection.send_result(msg["id"], {"state": new_state})
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
    """Get power value from an entity."""
    state = hass.states.get(entity_id)
    if state is None:
        return 0.0

    # Sensor entity - power is the state value
    if entity_id.startswith("sensor."):
        try:
            if state.state not in ("unknown", "unavailable", ""):
                return float(state.state)
        except (ValueError, TypeError):
            pass
        return 0.0

    # Switch entity - power is an attribute
    if entity_id.startswith("switch."):
        power = state.attributes.get("current_power_w", 0)
        try:
            return float(power)
        except (ValueError, TypeError):
            return 0.0

    return 0.0
