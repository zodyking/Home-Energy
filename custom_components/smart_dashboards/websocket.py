"""WebSocket API for Smart Dashboards."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Server-side cache for get_statistics (60s TTL) to avoid heavy recorder queries
_STATISTICS_CACHE: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}
_STATISTICS_CACHE_TTL = 60.0


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
    result: dict[str, Any] = {
        "rooms": [],
        "total_warnings": event_counts.get("total_warnings", 0),
        "total_shutoffs": event_counts.get("total_shutoffs", 0),
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
                # Light: switch state for on/off display; when on, sum watts from mapped lights
                switch_entity = outlet.get("switch_entity")
                if switch_entity:
                    state = hass.states.get(switch_entity)
                    is_on = bool(state and (state.state or "off").lower() in ("on",))
                    outlet_data["switch_state"] = is_on
                    if is_on:
                        light_ents = outlet.get("light_entities") or []
                        total_watts = 0.0
                        total_day_wh = 0.0
                        tracking_key = f"light_{room_id}_{(outlet.get('name') or 'light').lower().replace(' ', '_')}"
                        for le in light_ents:
                            if isinstance(le, dict) and le.get("entity_id", "").startswith("light."):
                                total_watts += float(le.get("watts", 0) or 0)
                        total_day_wh = config_manager.get_day_energy(tracking_key)
                        outlet_data["plug1"] = {"watts": total_watts, "day_wh": round(total_day_wh, 2)}
                        room_data["total_watts"] += total_watts
                        room_data["total_day_wh"] += total_day_wh
                else:
                    outlet_data["switch_state"] = False
            elif outlet_type == "ceiling_vent_fan":
                # Ceiling vent: switch + predefined watts when on
                switch_entity = outlet.get("switch_entity")
                watts_when_on = float(outlet.get("watts_when_on", 0) or 0)
                if switch_entity:
                    state = hass.states.get(switch_entity)
                    is_on = bool(state and (state.state or "off").lower() in ("on",))
                    watts = watts_when_on if is_on else 0.0
                else:
                    watts = 0.0
                tracking_key = f"ceiling_vent_{room_id}_{(outlet.get('name') or 'vent').lower().replace(' ', '_')}"
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

            room_data["outlets"].append(outlet_data)

        room_data["total_watts"] = round(room_data["total_watts"], 1)
        room_data["total_day_wh"] = round(room_data["total_day_wh"], 2)
        result["rooms"].append(room_data)

    connection.send_result(msg["id"], result)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "smart_dashboards/get_daily_history",
        vol.Optional("days", default=30): int,
    }
)
@websocket_api.async_response
async def websocket_get_daily_history(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Get last N days of daily totals for 30-day graphs."""
    config_manager = hass.data[DOMAIN].get("config_manager")
    if not config_manager:
        connection.send_error(msg["id"], "not_ready", "Config manager not initialized")
        return
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
                if outlet.get("type") == "ceiling_vent_fan":
                    switch_entity = outlet.get("switch_entity")
                    watts_when_on = float(outlet.get("watts_when_on", 0) or 0)
                    if switch_entity and watts_when_on > 0:
                        state = hass.states.get(switch_entity)
                        if state and (state.state or "off").lower() in ("on",):
                            current_watts += watts_when_on
                elif outlet.get("type") != "light":
                    for eid in (outlet.get("plug1_entity"), outlet.get("plug2_entity")):
                        if eid:
                            current_watts += _get_power(eid)
        data = {"timestamps": [now], "watts": [current_watts]}
    
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
    }
)
@websocket_api.async_response
async def websocket_get_event_log(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Get event log (warnings/shutoffs with TTS success/fail) for dashboard log modal."""
    config_manager = hass.data[DOMAIN].get("config_manager")
    if not config_manager:
        connection.send_error(msg["id"], "not_ready", "Config manager not initialized")
        return
    room_id = msg.get("room_id")
    since_hours = msg.get("since_hours", 24)
    events = config_manager.get_event_log(room_id=room_id, since_hours=since_hours)
    connection.send_result(msg["id"], {"events": events})


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


def _integrate_power_to_wh(
    entity_states: list, entity_id: str
) -> float:
    """Integrate power (W) over time using trapezoidal rule. Returns Wh."""
    if not entity_states or len(entity_states) < 2:
        return 0.0
    total_wh = 0.0
    for i in range(1, len(entity_states)):
        s1, s2 = entity_states[i - 1], entity_states[i]
        try:
            unit1 = s1.attributes.get("unit_of_measurement") if hasattr(s1, "attributes") else None
            unit2 = s2.attributes.get("unit_of_measurement") if hasattr(s2, "attributes") else None
            w1 = _parse_power_from_state(s1.state, unit1)
            w2 = _parse_power_from_state(s2.state, unit2)
        except (AttributeError, TypeError):
            continue
        dt_sec = (s2.last_updated - s1.last_updated).total_seconds()
        if dt_sec <= 0:
            continue
        # Trapezoidal: (w1 + w2) / 2 * hours
        total_wh += (w1 + w2) / 2.0 * (dt_sec / 3600.0)
    return total_wh


def _compute_kwh_from_history_sync(
    hass: HomeAssistant,
    entity_to_room: dict[str, str],
    start_dt,  # datetime
    end_dt,  # datetime
) -> tuple[float, dict[str, float]]:
    """Synchronous core: query recorder history and integrate power to Wh.
    Returns (total_wh, room_wh_map)."""
    from homeassistant.components.recorder.history import get_significant_states_with_session
    from homeassistant.components.recorder.util import session_scope

    entity_ids = list(entity_to_room.keys())
    if not entity_ids:
        return 0.0, {}

    with session_scope(hass=hass, read_only=True) as session:
        states_dict = get_significant_states_with_session(
            hass,
            session,
            start_dt,
            end_dt,
            entity_ids,
            None,
            include_start_time_state=True,
            significant_changes_only=False,
            minimal_response=False,
            no_attributes=False,
        )

    room_wh: dict[str, float] = {}
    total_wh = 0.0
    for eid, states in states_dict.items():
        wh = _integrate_power_to_wh(states, eid)
        room_id = entity_to_room.get(eid)
        if room_id:
            room_wh[room_id] = room_wh.get(room_id, 0.0) + wh
        total_wh += wh
    return total_wh, room_wh


async def _compute_kwh_from_history(
    hass: HomeAssistant,
    config_manager,
    start_date: str,
    end_date: str,
) -> tuple[float, dict[str, float]]:
    """Compute kWh from HA recorder history over start_date..end_date.
    Returns (total_wh, room_wh_map)."""
    from homeassistant.components.recorder import get_instance
    from homeassistant.util import dt as dt_util

    # Collect entity_ids and room mapping from room config
    entity_to_room: dict[str, str] = {}
    for room in config_manager.energy_config.get("rooms", []):
        room_id = room.get("id", room["name"].lower().replace(" ", "_"))
        for outlet in room.get("outlets", []):
            if outlet.get("type") == "light":
                continue
            for eid in (outlet.get("plug1_entity"), outlet.get("plug2_entity")):
                if eid and isinstance(eid, str) and eid.strip():
                    entity_to_room[eid.strip()] = room_id

    if not entity_to_room:
        return 0.0, {}

    # Parse date range to UTC datetimes
    try:
        start_dt = dt_util.parse_datetime(f"{start_date} 00:00:00")
        end_dt = dt_util.parse_datetime(f"{end_date} 23:59:59")
        if start_dt is None or end_dt is None:
            return 0.0, {}
        start_dt = dt_util.as_utc(start_dt)
        end_dt = dt_util.as_utc(end_dt)
    except (ValueError, TypeError):
        return 0.0, {}

    return await get_instance(hass).async_add_executor_job(
        _compute_kwh_from_history_sync,
        hass,
        entity_to_room,
        start_dt,
        end_dt,
    )


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
    start, end, is_narrowed = config_manager.get_statistics_date_range(
        date_start=date_start, date_end=date_end
    )

    # Return cached result if valid (avoids heavy recorder query)
    cache_key = (start or "", end or "")
    now = time.monotonic()
    if cache_key[0] and cache_key[1]:
        entry = _STATISTICS_CACHE.get(cache_key)
        if entry:
            cached_at, cached_result = entry
            if now - cached_at < _STATISTICS_CACHE_TTL:
                connection.send_result(msg["id"], cached_result)
                return

    result: dict[str, Any] = {
        "date_start": start,
        "date_end": end,
        "is_narrowed": is_narrowed,
        "total_kwh": 0.0,
        "total_warnings": 0,
        "total_shutoffs": 0,
        "rooms": [],
        "sensor_values": {
            "current_usage": None,
            "projected_usage": None,
            "kwh_cost": None,
        },
    }

    # Record billing cycle if changed
    billing_start, billing_end = config_manager.get_billing_date_range()
    if billing_start and billing_end:
        await config_manager.record_billing_cycle_if_changed(billing_start, billing_end)

    if not start or not end:
        connection.send_result(msg["id"], result)
        return

    # kWh from HA recorder history (same source as sensor graphs)
    try:
        total_wh, room_wh_map = await _compute_kwh_from_history(
            hass, config_manager, start, end
        )
    except Exception as err:  # recorder not ready or history unavailable
        _LOGGER.warning("Statistics kWh from history failed: %s", err)
        total_wh = 0.0
        room_wh_map = {}
    total_kwh = total_wh / 1000.0 if total_wh else 0.0

    # Warnings and shutoffs from daily_totals
    from homeassistant.util import dt as dt_util
    today = dt_util.now().strftime("%Y-%m-%d")
    daily_totals = config_manager.daily_totals
    all_dates = set(daily_totals.keys())
    if start <= today <= end:
        all_dates.add(today)
    dates_sorted = sorted(all_dates)
    range_dates = [d for d in dates_sorted if start <= d <= end]

    total_warnings = 0
    total_shutoffs = 0
    room_sums: dict[str, dict[str, Any]] = {}

    for rid in room_wh_map:
        room_sums[rid] = {
            "kwh": room_wh_map[rid] / 1000.0,
            "warnings": 0,
            "shutoffs": 0,
        }

    for d in range_dates:
        if d == today:
            row = config_manager._build_today_totals()
        else:
            row = daily_totals.get(d, {})
        total_warnings += int(row.get("total_warnings", 0))
        total_shutoffs += int(row.get("total_shutoffs", 0))
        row_rooms = row.get("rooms") or {}
        for rid, rdata in row_rooms.items():
            if rid not in room_sums:
                room_sums[rid] = {"kwh": 0.0, "warnings": 0, "shutoffs": 0}
            room_sums[rid]["warnings"] += int(rdata.get("warnings", 0))
            room_sums[rid]["shutoffs"] += int(rdata.get("shutoffs", 0))
    result["total_kwh"] = round(total_kwh, 2)
    result["total_warnings"] = total_warnings
    result["total_shutoffs"] = total_shutoffs

    # Build rooms list with name and percentage
    rooms_config = config_manager.energy_config.get("rooms", [])
    for room in rooms_config:
        rid = room.get("id", room["name"].lower().replace(" ", "_"))
        name = room.get("name", rid)
        rsum = room_sums.get(rid, {"kwh": 0.0, "warnings": 0, "shutoffs": 0})
        kwh = round(rsum["kwh"], 2)
        pct = round((kwh / total_kwh * 100) if total_kwh > 0 else 0, 1)
        result["rooms"].append({
            "id": rid,
            "name": name,
            "kwh": kwh,
            "pct": pct,
            "warnings": rsum["warnings"],
            "shutoffs": rsum["shutoffs"],
        })

    # Add any rooms in daily totals that aren't in config
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
            })

    # Read live sensor values (sensors + input_text, input_number helpers)
    stats = config_manager.energy_config.get("statistics_settings", {})
    for key, sensor_key in [
        ("current_usage", "current_usage_sensor"),
        ("projected_usage", "projected_usage_sensor"),
        ("kwh_cost", "kwh_cost_sensor"),
    ]:
        ent = (stats.get(sensor_key) or "").strip()
        if ent:
            state = hass.states.get(ent)
            if state and state.state not in ("unknown", "unavailable", ""):
                try:
                    val = str(state.state).strip()
                    if key == "kwh_cost":
                        val = val.replace("$", "").replace(",", "").strip()
                    result["sensor_values"][key] = float(val)
                except (ValueError, TypeError):
                    pass

    if cache_key[0] and cache_key[1]:
        _STATISTICS_CACHE[cache_key] = (now, result)

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
