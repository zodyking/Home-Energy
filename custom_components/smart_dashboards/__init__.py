"""The Smart Dashboards integration."""
from __future__ import annotations

import logging
import os

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import StaticPathConfig

from .const import (
    DOMAIN,
    CAMERAS_PANEL_ICON,
    CAMERAS_PANEL_TITLE,
    CAMERAS_PANEL_URL,
    ENERGY_PANEL_ICON,
    ENERGY_PANEL_TITLE,
    ENERGY_PANEL_URL,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Smart Dashboards from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN]["entry_id"] = entry.entry_id
    hass.data[DOMAIN]["options"] = dict(entry.options or {})

    # Initialize config manager
    from .config_manager import ConfigManager
    config_manager = ConfigManager(hass)
    await config_manager.async_load()
    hass.data[DOMAIN]["config_manager"] = config_manager

    # Register WebSocket API
    from .websocket import async_setup as async_setup_websocket
    async_setup_websocket(hass)

    # Register sidebar panels based on user options
    await async_register_panels(hass, entry)

    # Start energy monitor (only if energy panel is enabled)
    if entry.options.get("enable_energy", True):
        from .energy_monitor import async_start_energy_monitor
        await async_start_energy_monitor(hass, config_manager)

    # Listen for options updates
    entry.async_on_unload(entry.add_update_listener(async_options_update_listener))

    return True


async def async_options_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update - re-register panels."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    # Stop energy monitor
    if "energy_monitor_task" in hass.data.get(DOMAIN, {}):
        hass.data[DOMAIN]["energy_monitor_task"].cancel()

    # Remove panels (only if they were registered)
    try:
        frontend.async_remove_panel(hass, CAMERAS_PANEL_URL)
    except KeyError:
        pass
    try:
        frontend.async_remove_panel(hass, ENERGY_PANEL_URL)
    except KeyError:
        pass

    # Clean up data
    hass.data.pop(DOMAIN, None)

    return True


async def async_register_panels(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Register the sidebar panels based on user options."""
    # Get user options
    enable_cameras = entry.options.get("enable_cameras", True)
    enable_energy = entry.options.get("enable_energy", True)

    # Get the path to our panel JS files
    frontend_path = os.path.join(os.path.dirname(__file__), "frontend")
    panel_url = f"/{DOMAIN}_panel"

    # Register static path for the panel files
    await hass.http.async_register_static_paths([
        StaticPathConfig(panel_url, frontend_path, cache_headers=False)
    ])

    # Register Cameras Panel (if enabled)
    if enable_cameras:
        if CAMERAS_PANEL_URL not in hass.data.get("frontend_panels", {}):
            await panel_custom.async_register_panel(
                hass,
                webcomponent_name="cameras-panel",
                frontend_url_path=CAMERAS_PANEL_URL,
                sidebar_title=CAMERAS_PANEL_TITLE,
                sidebar_icon=CAMERAS_PANEL_ICON,
                module_url=f"{panel_url}/cameras-panel.js",
                embed_iframe=False,
                require_admin=False,
            )
            _LOGGER.info("Registered Cameras panel")
    else:
        # Remove panel if it was previously registered
        try:
            frontend.async_remove_panel(hass, CAMERAS_PANEL_URL)
            _LOGGER.info("Removed Cameras panel (disabled)")
        except KeyError:
            pass

    # Register Energy Panel (if enabled)
    if enable_energy:
        if ENERGY_PANEL_URL not in hass.data.get("frontend_panels", {}):
            await panel_custom.async_register_panel(
                hass,
                webcomponent_name="energy-panel",
                frontend_url_path=ENERGY_PANEL_URL,
                sidebar_title=ENERGY_PANEL_TITLE,
                sidebar_icon=ENERGY_PANEL_ICON,
                module_url=f"{panel_url}/energy-panel.js",
                embed_iframe=False,
                require_admin=False,
            )
            _LOGGER.info("Registered Energy panel")
    else:
        # Remove panel if it was previously registered
        try:
            frontend.async_remove_panel(hass, ENERGY_PANEL_URL)
            _LOGGER.info("Removed Energy panel (disabled)")
        except KeyError:
            pass
