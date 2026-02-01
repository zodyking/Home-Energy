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
    websocket_api.async_register_command(hass, websocket_save_cameras)
    websocket_api.async_register_command(hass, websocket_save_energy)
    websocket_api.async_register_command(hass, websocket_get_entities)
    websocket_api.async_register_command(hass, websocket_send_tts)
    websocket_api.async_register_command(hass, websocket_set_volume)
    websocket_api.async_register_command(hass, websocket_get_power_data)
    websocket_api.async_register_command(hass, websocket_get_camera_stream_url)
    websocket_api.async_register_command(hass, websocket_get_entities_by_area)
    websocket_api.async_register_command(hass, websocket_get_areas)
    websocket_api.async_register_command(hass, websocket_get_switches)
    websocket_api.async_register_command(hass, websocket_verify_passcode)
    websocket_api.async_register_command(hass, websocket_toggle_switch)
    websocket_api.async_register_command(hass, websocket_get_breaker_data)
    websocket_api.async_register_command(hass, websocket_test_trip_breaker)
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
        vol.Required("type"): "smart_dashboards/save_cameras",
        vol.Required("config"): dict,
    }
)
@websocket_api.async_response
async def websocket_save_cameras(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Save cameras configuration."""
    config_manager = hass.data[DOMAIN].get("config_manager")
    if config_manager:
        await config_manager.async_update_cameras(msg["config"])
        connection.send_result(msg["id"], {"success": True})
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
    """Get available entities (cameras, media players, power sensors)."""
    entity_type = msg.get("entity_type")
    result: dict[str, list[dict[str, str]]] = {
        "cameras": [],
        "media_players": [],
        "power_sensors": [],
    }

    for state in hass.states.async_all():
        entity_id = state.entity_id
        friendly_name = state.attributes.get("friendly_name", entity_id)

        if entity_type is None or entity_type == "camera":
            if entity_id.startswith("camera."):
                result["cameras"].append({
                    "entity_id": entity_id,
                    "friendly_name": friendly_name,
                })

        if entity_type is None or entity_type == "media_player":
            if entity_id.startswith("media_player."):
                result["media_players"].append({
                    "entity_id": entity_id,
                    "friendly_name": friendly_name,
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
            outlet_data = {
                "name": outlet["name"],
                "plug1": {"watts": 0, "day_wh": 0},
                "plug2": {"watts": 0, "day_wh": 0},
            }

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
        vol.Required("type"): "smart_dashboards/get_camera_stream_url",
        vol.Required("entity_id"): str,
    }
)
@websocket_api.async_response
async def websocket_get_camera_stream_url(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Get camera stream URL."""
    entity_id = msg["entity_id"]
    
    # Check if entity exists
    state = hass.states.get(entity_id)
    if state is None:
        connection.send_error(msg["id"], "entity_not_found", f"Camera {entity_id} not found")
        return

    # Return the stream proxy URL
    connection.send_result(msg["id"], {
        "stream_url": f"/api/camera_proxy_stream/{entity_id}",
        "snapshot_url": f"/api/camera_proxy/{entity_id}",
    })


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
        }

        # Calculate total power for this breaker
        for outlet in outlets:
            if outlet.get("plug1_entity"):
                watts = _get_power_value(hass, outlet["plug1_entity"])
                day_wh = config_manager.get_day_energy(outlet["plug1_entity"])
                breaker_data["total_watts"] += watts
                breaker_data["total_day_wh"] += day_wh
            if outlet.get("plug2_entity"):
                watts = _get_power_value(hass, outlet["plug2_entity"])
                day_wh = config_manager.get_day_energy(outlet["plug2_entity"])
                breaker_data["total_watts"] += watts
                breaker_data["total_day_wh"] += day_wh

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
    
    # Check current state of switches to determine toggle action
    # If any switch is on, turn all off. If all are off, turn all on.
    any_on = False
    for entity_id in switch_entities:
        state = hass.states.get(entity_id)
        if state and state.state == "on":
            any_on = True
            break
    
    # Determine service and new state
    if any_on:
        service = "turn_off"
        new_state = "off"
    else:
        service = "turn_on"
        new_state = "on"
    
    try:
        # Single service call with all entity IDs in a list
        await hass.services.async_call(
            "switch",
            service,
            {"entity_id": switch_entities},
            blocking=True,
        )
        
        connection.send_result(msg["id"], {
            "success": True,
            "total_switches": len(switch_entities),
            "state": new_state,
            "action": service,
        })
    except Exception as e:
        _LOGGER.error("Test trip breaker failed: %s", e)
        connection.send_error(msg["id"], "trip_failed", str(e))


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
