"""Configuration manager for Smart Dashboards."""
from __future__ import annotations

import json
import logging
import os
from copy import deepcopy
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import CONFIG_FILE, DEFAULT_CONFIG, DOMAIN

_LOGGER = logging.getLogger(__name__)


class ConfigManager:
    """Manage Smart Dashboards configuration stored in JSON file."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the config manager."""
        self.hass = hass
        self._config: dict[str, Any] = deepcopy(DEFAULT_CONFIG)
        self._config_path = hass.config.path(CONFIG_FILE)
        self._day_energy_data: dict[str, dict[str, float]] = {}
        self._last_reset_date: str | None = None

    @property
    def config(self) -> dict[str, Any]:
        """Return the current configuration."""
        return self._config

    @property
    def cameras_config(self) -> dict[str, Any]:
        """Return cameras configuration."""
        return self._config.get("cameras", DEFAULT_CONFIG["cameras"])

    @property
    def energy_config(self) -> dict[str, Any]:
        """Return energy configuration."""
        return self._config.get("energy", DEFAULT_CONFIG["energy"])

    async def async_load(self) -> None:
        """Load configuration from file."""
        try:
            if os.path.exists(self._config_path):
                with open(self._config_path, "r", encoding="utf-8") as f:
                    loaded_config = json.load(f)
                    self._config = self._merge_with_defaults(loaded_config)
                    _LOGGER.info("Loaded Smart Dashboards configuration")
            else:
                _LOGGER.info("No config file found, using defaults")
                await self.async_save()
        except (json.JSONDecodeError, IOError) as err:
            _LOGGER.error("Error loading config: %s", err)
            self._config = deepcopy(DEFAULT_CONFIG)

        # Load day energy tracking data
        await self._async_load_energy_tracking()

    async def async_save(self) -> None:
        """Save configuration to file."""
        try:
            with open(self._config_path, "w", encoding="utf-8") as f:
                json.dump(self._config, f, indent=2)
            _LOGGER.debug("Saved Smart Dashboards configuration")
        except IOError as err:
            _LOGGER.error("Error saving config: %s", err)

    def _merge_with_defaults(self, loaded: dict[str, Any]) -> dict[str, Any]:
        """Merge loaded config with defaults to ensure all keys exist."""
        result = deepcopy(DEFAULT_CONFIG)

        # Merge cameras config
        if "cameras" in loaded:
            cameras = loaded["cameras"]
            result["cameras"]["main_camera"] = cameras.get("main_camera")
            result["cameras"]["sub_cameras"] = cameras.get("sub_cameras", [])
            if "tts_settings" in cameras:
                result["cameras"]["tts_settings"].update(cameras["tts_settings"])

        # Merge energy config
        if "energy" in loaded:
            energy = loaded["energy"]
            result["energy"]["rooms"] = energy.get("rooms", [])
            if "tts_settings" in energy:
                result["energy"]["tts_settings"].update(energy["tts_settings"])

        return result

    async def async_update_cameras(self, cameras_config: dict[str, Any]) -> None:
        """Update cameras configuration."""
        self._config["cameras"] = self._validate_cameras_config(cameras_config)
        await self.async_save()

    async def async_update_energy(self, energy_config: dict[str, Any]) -> None:
        """Update energy configuration."""
        self._config["energy"] = self._validate_energy_config(energy_config)
        await self.async_save()

    def _validate_cameras_config(self, config: dict[str, Any]) -> dict[str, Any]:
        """Validate and sanitize cameras configuration."""
        validated = deepcopy(DEFAULT_CONFIG["cameras"])

        # Validate main camera
        main_camera = config.get("main_camera")
        if main_camera and isinstance(main_camera, dict):
            validated["main_camera"] = {
                "entity_id": main_camera.get("entity_id"),
                "media_player": main_camera.get("media_player"),
            }
        elif main_camera and isinstance(main_camera, str):
            validated["main_camera"] = {
                "entity_id": main_camera,
                "media_player": None,
            }

        # Validate sub cameras
        sub_cameras = config.get("sub_cameras", [])
        validated["sub_cameras"] = []
        for cam in sub_cameras:
            if isinstance(cam, dict) and cam.get("entity_id"):
                validated["sub_cameras"].append({
                    "entity_id": cam["entity_id"],
                    "media_player": cam.get("media_player"),
                })

        # Validate TTS settings
        tts = config.get("tts_settings", {})
        validated["tts_settings"] = {
            "language": tts.get("language", DEFAULT_CONFIG["cameras"]["tts_settings"]["language"]),
            "speed": float(tts.get("speed", DEFAULT_CONFIG["cameras"]["tts_settings"]["speed"])),
            "volume": float(tts.get("volume", DEFAULT_CONFIG["cameras"]["tts_settings"]["volume"])),
        }

        return validated

    def _validate_energy_config(self, config: dict[str, Any]) -> dict[str, Any]:
        """Validate and sanitize energy configuration."""
        validated = deepcopy(DEFAULT_CONFIG["energy"])

        # Validate rooms
        rooms = config.get("rooms", [])
        validated["rooms"] = []
        for room in rooms:
            if isinstance(room, dict) and room.get("name"):
                validated_room = {
                    "id": room.get("id", room["name"].lower().replace(" ", "_")),
                    "name": room["name"],
                    "area_id": room.get("area_id"),
                    "media_player": room.get("media_player"),
                    "threshold": int(room.get("threshold", 0)),
                    "volume": float(room.get("volume", 0.7)),
                    "outlets": [],
                }
                for outlet in room.get("outlets", []):
                    if isinstance(outlet, dict) and outlet.get("name"):
                        validated_room["outlets"].append({
                            "name": outlet["name"],
                            "plug1_entity": outlet.get("plug1_entity"),
                            "plug2_entity": outlet.get("plug2_entity"),
                            "plug1_switch": outlet.get("plug1_switch"),
                            "plug2_switch": outlet.get("plug2_switch"),
                            "threshold": int(outlet.get("threshold", 0)),
                            "plug1_shutoff": int(outlet.get("plug1_shutoff", 0)),
                            "plug2_shutoff": int(outlet.get("plug2_shutoff", 0)),
                        })
                validated["rooms"].append(validated_room)

        # Validate TTS settings
        tts = config.get("tts_settings", {})
        default_tts = DEFAULT_CONFIG["energy"]["tts_settings"]
        validated["tts_settings"] = {
            "language": tts.get("language", default_tts["language"]),
            "speed": float(tts.get("speed", default_tts["speed"])),
            "volume": float(tts.get("volume", default_tts["volume"])),
            "prefix": tts.get("prefix", default_tts["prefix"]),
            "room_warn_msg": tts.get("room_warn_msg", default_tts["room_warn_msg"]),
            "outlet_warn_msg": tts.get("outlet_warn_msg", default_tts["outlet_warn_msg"]),
            "shutoff_msg": tts.get("shutoff_msg", default_tts["shutoff_msg"]),
        }

        return validated

    # Day energy tracking
    async def _async_load_energy_tracking(self) -> None:
        """Load day energy tracking data."""
        tracking_path = self.hass.config.path("smart_dashboards_energy_tracking.json")
        try:
            if os.path.exists(tracking_path):
                with open(tracking_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._day_energy_data = data.get("outlets", {})
                    self._last_reset_date = data.get("last_reset_date")
        except (json.JSONDecodeError, IOError):
            pass

        # Check if we need to reset for a new day
        today = dt_util.now().strftime("%Y-%m-%d")
        if self._last_reset_date != today:
            self._day_energy_data = {}
            self._last_reset_date = today
            await self._async_save_energy_tracking()

    async def _async_save_energy_tracking(self) -> None:
        """Save day energy tracking data."""
        tracking_path = self.hass.config.path("smart_dashboards_energy_tracking.json")
        try:
            with open(tracking_path, "w", encoding="utf-8") as f:
                json.dump({
                    "last_reset_date": self._last_reset_date,
                    "outlets": self._day_energy_data,
                }, f, indent=2)
        except IOError as err:
            _LOGGER.error("Error saving energy tracking: %s", err)

    def get_day_energy(self, entity_id: str) -> float:
        """Get accumulated day energy for an entity."""
        return self._day_energy_data.get(entity_id, {}).get("energy", 0.0)

    async def async_add_energy_reading(self, entity_id: str, watts: float) -> None:
        """Add an energy reading (called every second)."""
        # Check for day reset
        today = dt_util.now().strftime("%Y-%m-%d")
        if self._last_reset_date != today:
            self._day_energy_data = {}
            self._last_reset_date = today

        # Accumulate energy (watts * 1 second = watt-seconds, convert to Wh)
        if entity_id not in self._day_energy_data:
            self._day_energy_data[entity_id] = {"energy": 0.0}

        # Add watt-seconds converted to watt-hours (1 Wh = 3600 Ws)
        self._day_energy_data[entity_id]["energy"] += watts / 3600

        # Save periodically (every 60 seconds to reduce disk writes)
        # This is handled by the energy monitor
