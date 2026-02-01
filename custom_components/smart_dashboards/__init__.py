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

    # Initialize config manager
    from .config_manager import ConfigManager
    config_manager = ConfigManager(hass)
    await config_manager.async_load()
    hass.data[DOMAIN]["config_manager"] = config_manager

    # Register WebSocket API
    from .websocket import async_setup as async_setup_websocket
    async_setup_websocket(hass)

    # Register sidebar panels
    await async_register_panels(hass)

    # Start energy monitor
    from .energy_monitor import async_start_energy_monitor
    await async_start_energy_monitor(hass, config_manager)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    # Stop energy monitor
    if "energy_monitor_task" in hass.data[DOMAIN]:
        hass.data[DOMAIN]["energy_monitor_task"].cancel()

    # Remove panels
    frontend.async_remove_panel(hass, CAMERAS_PANEL_URL)
    frontend.async_remove_panel(hass, ENERGY_PANEL_URL)

    # Clean up data
    hass.data.pop(DOMAIN, None)

    return True


async def async_register_panels(hass: HomeAssistant) -> None:
    """Register the sidebar panels."""
    # Get the path to our panel JS files
    frontend_path = os.path.join(os.path.dirname(__file__), "frontend")
    panel_url = f"/{DOMAIN}_panel"

    # Register static path for the panel files
    await hass.http.async_register_static_paths([
        StaticPathConfig(panel_url, frontend_path, cache_headers=False)
    ])

    # Register Cameras Panel
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

    # Register Energy Panel
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
