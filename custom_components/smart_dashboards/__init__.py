"""The Home Energy integration."""
from __future__ import annotations

import json
import logging
import os
import time

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import StaticPathConfig

from .const import (
    DOMAIN,
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
    # Update stored options
    if DOMAIN in hass.data:
        hass.data[DOMAIN]["options"] = dict(entry.options or {})
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    # Stop energy monitor (unregister listeners, cancel task)
    energy_monitor = hass.data.get(DOMAIN, {}).get("energy_monitor")
    if energy_monitor:
        await energy_monitor.async_stop()

    # Persist energy and tracking data before cleanup (survives reload/restart)
    config_manager = hass.data.get(DOMAIN, {}).get("config_manager")
    if config_manager:
        await config_manager.async_save_persistent_data()

    # Remove panel (only if it was registered)
    try:
        frontend.async_remove_panel(hass, ENERGY_PANEL_URL)
    except KeyError:
        pass

    # Clean up data
    hass.data.pop(DOMAIN, None)

    return True


async def async_register_panels(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Register the sidebar panels based on user options."""
    enable_energy = entry.options.get("enable_energy", True)

    # Get the path to our panel JS files
    frontend_path = os.path.join(os.path.dirname(__file__), "frontend")
    panel_url = f"/{DOMAIN}_panel"

    # Read version from manifest for cache-busting (run in executor to avoid blocking event loop)
    def _read_manifest_version() -> str:
        manifest_path = os.path.join(os.path.dirname(__file__), "manifest.json")
        try:
            with open(manifest_path, encoding="utf-8") as f:
                return json.load(f).get("version", "1.0.0")
        except Exception:
            return "1.0.0"

    version = await hass.async_add_executor_job(_read_manifest_version)

    # Unique cache-bust per load so browser never serves cached dashboard JS
    load_id = str(int(time.time() * 1000))

    # Register static path for the panel files
    await hass.http.async_register_static_paths([
        StaticPathConfig(panel_url, frontend_path, cache_headers=False)
    ])

    # Register Energy Panel (if enabled)
    if enable_energy:
        if ENERGY_PANEL_URL not in hass.data.get("frontend_panels", {}):
            await panel_custom.async_register_panel(
                hass,
                webcomponent_name="energy-panel",
                frontend_url_path=ENERGY_PANEL_URL,
                sidebar_title=ENERGY_PANEL_TITLE,
                sidebar_icon=ENERGY_PANEL_ICON,
                module_url=f"{panel_url}/energy-panel.js?v={version}&_={load_id}",
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
