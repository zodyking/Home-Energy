"""WebSocket API for Smart Dashboards."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


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
    if config_manager:
        await config_manager.async_update_energy(msg["config"])
        connection.send_result(msg["id"], {"success": True})
    else:
        connection.send_error(msg["id"], "not_ready", "Config manager not initialized")


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
    """Send TTS to a media player."""
    from .tts_helper import async_send_tts

    try:
        await async_send_tts(
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
                    is_on = (state.state or "off").lower() in ("on",)
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

    # Aggregate from daily totals + today's live data
    from homeassistant.util import dt as dt_util
    today = dt_util.now().strftime("%Y-%m-%d")
    daily_totals = config_manager.daily_totals
    # Include today in the date list if it's within range
    all_dates = set(daily_totals.keys())
    if start <= today <= end:
        all_dates.add(today)
    dates_sorted = sorted(all_dates)
    range_dates = [d for d in dates_sorted if start <= d <= end]

    total_wh = 0.0
    total_warnings = 0
    total_shutoffs = 0
    room_sums: dict[str, dict[str, Any]] = {}

    for d in range_dates:
        # Use live data for today, historical data for past days
        if d == today:
            row = config_manager._build_today_totals()
        else:
            row = daily_totals.get(d, {})
        total_wh += float(row.get("total_wh", 0))
        total_warnings += int(row.get("total_warnings", 0))
        total_shutoffs += int(row.get("total_shutoffs", 0))
        row_rooms = row.get("rooms") or {}
        for rid, rdata in row_rooms.items():
            if rid not in room_sums:
                room_sums[rid] = {"kwh": 0.0, "warnings": 0, "shutoffs": 0}
            room_sums[rid]["kwh"] += float(rdata.get("wh", 0)) / 1000.0
            room_sums[rid]["warnings"] += int(rdata.get("warnings", 0))
            room_sums[rid]["shutoffs"] += int(rdata.get("shutoffs", 0))

    total_kwh = total_wh / 1000.0 if total_wh else 0.0
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
