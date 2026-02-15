"""Configuration manager for Smart Dashboards."""
from __future__ import annotations

import json
import logging
import os
import re
from copy import deepcopy
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import CONFIG_FILE, DEFAULT_CONFIG, DOMAIN, DEFAULT_TTS_VOLUME

_LOGGER = logging.getLogger(__name__)


def _validate_rgb(val: Any) -> list[int]:
    """Validate and return RGB list [r, g, b] 0-255."""
    if isinstance(val, list) and len(val) >= 3:
        return [
            max(0, min(255, int(val[0]) if val[0] is not None else 0)),
            max(0, min(255, int(val[1]) if val[1] is not None else 0)),
            max(0, min(255, int(val[2]) if val[2] is not None else 0)),
        ]
    return [245, 0, 0]


def _load_json_file(path: str) -> dict | None:
    """Load JSON file (run in executor to avoid blocking event loop)."""
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_json_file(path: str, data: Any) -> None:
    """Write JSON file (run in executor to avoid blocking event loop)."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


class ConfigManager:
    """Manage Smart Dashboards configuration stored in JSON file."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the config manager."""
        self.hass = hass
        self._config: dict[str, Any] = deepcopy(DEFAULT_CONFIG)
        self._config_path = hass.config.path(CONFIG_FILE)
        self._day_energy_data: dict[str, dict[str, float]] = {}
        self._last_reset_date: str | None = None
        self._event_counts_reset_date: str | None = None
        self._event_counts: dict[str, Any] = {
            "total_warnings": 0,
            "total_shutoffs": 0,
            "room_warnings": {},  # room_id -> count (today only)
            "room_shutoffs": {},  # room_id -> count (today only)
        }
        self._daily_totals: dict[str, Any] = {}
        self._billing_history: dict[str, Any] = {
            "cycles": [],
            "last_billing_start": "",
            "last_billing_end": "",
        }
        self._last_power_update: dict[str, dict] = {}  # entity_id -> {watts, time}

    @property
    def config(self) -> dict[str, Any]:
        """Return the current configuration."""
        return self._config

    @property
    def energy_config(self) -> dict[str, Any]:
        """Return energy configuration."""
        return self._config.get("energy", DEFAULT_CONFIG["energy"])

    @property
    def daily_totals(self) -> dict[str, Any]:
        """Return daily totals history (read-only)."""
        return self._daily_totals

    async def async_load(self) -> None:
        """Load configuration from file."""
        try:
            loaded_config = await self.hass.async_add_executor_job(
                _load_json_file, self._config_path
            )
            if loaded_config is not None:
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
        # Load event counts
        await self._async_load_event_counts()
        # Load daily totals history
        await self._async_load_daily_totals()
        # Load billing history
        await self._async_load_billing_history()

    async def async_save(self) -> None:
        """Save configuration to file."""
        try:
            await self.hass.async_add_executor_job(
                _write_json_file, self._config_path, self._config
            )
            _LOGGER.debug("Saved Smart Dashboards configuration")
        except IOError as err:
            _LOGGER.error("Error saving config: %s", err)

    def _merge_with_defaults(self, loaded: dict[str, Any]) -> dict[str, Any]:
        """Merge loaded config with defaults to ensure all keys exist."""
        result = deepcopy(DEFAULT_CONFIG)

        # Merge energy config
        if "energy" in loaded:
            energy = loaded["energy"]
            result["energy"]["rooms"] = energy.get("rooms", [])
            result["energy"]["breaker_lines"] = energy.get("breaker_lines", [])
            # Migrate legacy stove_safety to first stove device (and microwave in same room)
            legacy_stove = energy.get("stove_safety", {})
            if legacy_stove and any(v for v in legacy_stove.values() if v):
                for room in result["energy"]["rooms"]:
                    outlets = room.get("outlets", [])
                    stove_outlet = next((o for o in outlets if o.get("type") == "stove"), None)
                    if stove_outlet:
                        stove_outlet["plug1_entity"] = stove_outlet.get("plug1_entity") or legacy_stove.get("stove_plug_entity")
                        stove_outlet["plug1_switch"] = stove_outlet.get("plug1_switch") or legacy_stove.get("stove_plug_switch")
                        stove_outlet["stove_power_threshold"] = stove_outlet.get("stove_power_threshold", legacy_stove.get("stove_power_threshold", 100))
                        stove_outlet["cooking_time_minutes"] = stove_outlet.get("cooking_time_minutes", legacy_stove.get("cooking_time_minutes", 15))
                        stove_outlet["final_warning_seconds"] = stove_outlet.get("final_warning_seconds", legacy_stove.get("final_warning_seconds", 30))
                        stove_outlet["presence_sensor"] = stove_outlet.get("presence_sensor") or legacy_stove.get("presence_sensor")
                        # Media player and volume come from room; migrate legacy to room
                        if legacy_stove.get("media_player"):
                            room["media_player"] = legacy_stove["media_player"]
                        if legacy_stove.get("volume") is not None:
                            room["volume"] = float(legacy_stove["volume"])
                        if legacy_stove.get("microwave_plug_entity"):
                            for mw in outlets:
                                if mw.get("type") == "microwave":
                                    mw["plug1_entity"] = mw.get("plug1_entity") or legacy_stove.get("microwave_plug_entity")
                                    mw["microwave_power_threshold"] = mw.get("microwave_power_threshold", legacy_stove.get("microwave_power_threshold", 50))
                                    break
                        break
            if "tts_settings" in energy:
                result["energy"]["tts_settings"].update(energy["tts_settings"])
            if "statistics_settings" in energy:
                for k, v in energy["statistics_settings"].items():
                    if k in result["energy"]["statistics_settings"] and v:
                        result["energy"]["statistics_settings"][k] = str(v).strip()

        return result

    async def async_update_energy(self, energy_config: dict[str, Any]) -> None:
        """Update energy configuration."""
        self._config["energy"] = self._validate_energy_config(energy_config)
        await self.async_save()

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
                    "responsive_light_warnings": bool(room.get("responsive_light_warnings", False)),
                    "responsive_light_color": _validate_rgb(room.get("responsive_light_color")),
                    "responsive_light_temp": max(2000, min(6500, int(room.get("responsive_light_temp", 6500)))),
                    "responsive_light_interval": max(0.1, min(10.0, float(room.get("responsive_light_interval", 1.5)))),
                    "outlets": [],
                }
                for outlet in room.get("outlets", []):
                    if isinstance(outlet, dict) and outlet.get("name"):
                        outlet_type = outlet.get("type", "outlet")
                        if outlet_type not in ("outlet", "single_outlet", "stove", "microwave", "minisplit", "light"):
                            outlet_type = "outlet"
                        item = {
                            "name": outlet["name"],
                            "type": outlet_type,
                            "plug1_entity": outlet.get("plug1_entity"),
                            "threshold": int(outlet.get("threshold", 0)),
                        }
                        if outlet_type == "outlet":
                            item["plug2_entity"] = outlet.get("plug2_entity")
                            item["plug1_switch"] = outlet.get("plug1_switch")
                            item["plug2_switch"] = outlet.get("plug2_switch")
                            item["plug1_shutoff"] = int(outlet.get("plug1_shutoff", 0))
                            item["plug2_shutoff"] = int(outlet.get("plug2_shutoff", 0))
                        elif outlet_type == "stove":
                            item["plug2_entity"] = None
                            item["plug1_switch"] = outlet.get("plug1_switch")
                            item["plug2_switch"] = None
                            item["plug1_shutoff"] = 0
                            item["plug2_shutoff"] = 0
                            item["stove_safety_enabled"] = outlet.get("stove_safety_enabled", True)
                            item["stove_power_threshold"] = int(outlet.get("stove_power_threshold", 100))
                            item["cooking_time_minutes"] = int(outlet.get("cooking_time_minutes", 15))
                            item["final_warning_seconds"] = int(outlet.get("final_warning_seconds", 30))
                            item["presence_sensor"] = outlet.get("presence_sensor")
                        elif outlet_type == "microwave":
                            item["plug2_entity"] = None
                            item["plug1_switch"] = None
                            item["plug2_switch"] = None
                            item["plug1_shutoff"] = 0
                            item["plug2_shutoff"] = 0
                            item["microwave_safety_enabled"] = outlet.get("microwave_safety_enabled", False)
                            item["microwave_power_threshold"] = int(outlet.get("microwave_power_threshold", 50))
                        elif outlet_type == "light":
                            item["plug1_entity"] = None
                            item["plug2_entity"] = None
                            item["plug1_switch"] = None
                            item["plug2_switch"] = None
                            item["plug1_shutoff"] = 0
                            item["plug2_shutoff"] = 0
                            item["switch_entity"] = outlet.get("switch_entity")
                            light_ents = outlet.get("light_entities")
                            # Support list of {entity_id, watts} or legacy list of entity_id strings
                            if isinstance(light_ents, list):
                                by_entity = {}
                                for e in light_ents:
                                    eid = None
                                    w = 0
                                    if isinstance(e, dict) and e.get("entity_id", "").startswith("light."):
                                        eid = e["entity_id"]
                                        w = max(0, int(e.get("watts", 0)))
                                        wrgb = bool(e.get("wrgb", False))
                                        by_entity[eid] = {"entity_id": eid, "watts": w, "wrgb": wrgb}
                                    elif isinstance(e, str) and e.strip().startswith("light."):
                                        eid, w = e.strip(), 0
                                        if eid:
                                            by_entity[eid] = {"entity_id": eid, "watts": w, "wrgb": False}
                                item["light_entities"] = list(by_entity.values())
                            elif isinstance(light_ents, str):
                                item["light_entities"] = [
                                    {"entity_id": e.strip(), "watts": 0, "wrgb": False}
                                    for e in light_ents.split(",") if e.strip().startswith("light.")
                                ]
                            else:
                                item["light_entities"] = []
                        elif outlet_type in ("single_outlet", "minisplit"):
                            item["plug2_entity"] = None
                            item["plug1_switch"] = outlet.get("plug1_switch")
                            item["plug2_switch"] = None
                            item["plug1_shutoff"] = int(outlet.get("plug1_shutoff", 0))
                            item["plug2_shutoff"] = 0
                        else:
                            item["plug2_entity"] = None
                            item["plug1_switch"] = None
                            item["plug2_switch"] = None
                            item["plug1_shutoff"] = 0
                            item["plug2_shutoff"] = 0
                        validated_room["outlets"].append(item)
                validated["rooms"].append(validated_room)

        # Validate breaker panel size
        panel_size = config.get("breaker_panel_size", 20)
        validated["breaker_panel_size"] = max(2, min(40, int(panel_size))) if panel_size % 2 == 0 else 20

        # Validate breaker lines
        breaker_lines = config.get("breaker_lines", [])
        validated["breaker_lines"] = []
        for breaker in breaker_lines:
            if isinstance(breaker, dict) and breaker.get("name"):
                validated_breaker = {
                    "id": breaker.get("id", breaker["name"].lower().replace(" ", "_")),
                    "name": breaker["name"],
                    "number": max(1, min(validated["breaker_panel_size"], int(breaker.get("number", 1)))),
                    "color": breaker.get("color", "#03a9f4"),
                    "max_load": int(breaker.get("max_load", 2400)),
                    "threshold": int(breaker.get("threshold", 0)),
                    "outlet_ids": breaker.get("outlet_ids", []),  # List of outlet identifiers
                }
                validated["breaker_lines"].append(validated_breaker)

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
            "breaker_warn_msg": tts.get("breaker_warn_msg", default_tts["breaker_warn_msg"]),
            "breaker_shutoff_msg": tts.get("breaker_shutoff_msg", default_tts["breaker_shutoff_msg"]),
            "stove_on_msg": tts.get("stove_on_msg", default_tts["stove_on_msg"]),
            "stove_off_msg": tts.get("stove_off_msg", default_tts["stove_off_msg"]),
            "stove_timer_started_msg": tts.get("stove_timer_started_msg", default_tts["stove_timer_started_msg"]),
            "stove_15min_warn_msg": tts.get("stove_15min_warn_msg", default_tts["stove_15min_warn_msg"]),
            "stove_30sec_warn_msg": tts.get("stove_30sec_warn_msg", default_tts["stove_30sec_warn_msg"]),
            "stove_auto_off_msg": tts.get("stove_auto_off_msg", default_tts["stove_auto_off_msg"]),
            "microwave_cut_power_msg": tts.get("microwave_cut_power_msg", default_tts["microwave_cut_power_msg"]),
            "microwave_restore_power_msg": tts.get("microwave_restore_power_msg", default_tts["microwave_restore_power_msg"]),
        }

        # Validate statistics settings
        stats = config.get("statistics_settings", {})
        default_stats = DEFAULT_CONFIG["energy"]["statistics_settings"]
        validated["statistics_settings"] = {
            "billing_start_sensor": (stats.get("billing_start_sensor") or "").strip(),
            "billing_end_sensor": (stats.get("billing_end_sensor") or "").strip(),
            "current_usage_sensor": (stats.get("current_usage_sensor") or "").strip(),
            "projected_usage_sensor": (stats.get("projected_usage_sensor") or "").strip(),
            "kwh_cost_sensor": (stats.get("kwh_cost_sensor") or "").strip(),
            "date_range_start": (stats.get("date_range_start") or "").strip(),
            "date_range_end": (stats.get("date_range_end") or "").strip(),
        }

        return validated

    # Day energy tracking
    async def _async_load_energy_tracking(self) -> None:
        """Load day energy tracking data."""
        tracking_path = self.hass.config.path("smart_dashboards_energy_tracking.json")
        try:
            data = await self.hass.async_add_executor_job(
                _load_json_file, tracking_path
            )
            if data is not None:
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
        payload = {
            "last_reset_date": self._last_reset_date,
            "outlets": self._day_energy_data,
        }
        try:
            await self.hass.async_add_executor_job(
                _write_json_file, tracking_path, payload
            )
        except IOError as err:
            _LOGGER.error("Error saving energy tracking: %s", err)

    def get_day_energy(self, entity_id: str) -> float:
        """Get accumulated day energy for an entity."""
        return self._day_energy_data.get(entity_id, {}).get("energy", 0.0)

    async def async_add_energy_reading(
        self, entity_id: str, watts: float, elapsed_seconds: float = 1.0
    ) -> None:
        """Add energy from a reading. Energy = watts * elapsed_seconds / 3600 (Wh).
        Called every second from poll (elapsed=1) or from state-change (elapsed=actual)."""
        today = dt_util.now().strftime("%Y-%m-%d")
        if self._last_reset_date != today:
            self._day_energy_data = {}
            self._last_reset_date = today
            self._last_power_update = {}

        if entity_id not in self._day_energy_data:
            self._day_energy_data[entity_id] = {"energy": 0.0}

        self._day_energy_data[entity_id]["energy"] += (watts * elapsed_seconds) / 3600.0

    async def async_add_energy_reading_on_state_change(
        self, entity_id: str, new_watts: float
    ) -> None:
        """Add energy when entity state changes (real-time). Uses elapsed time since
        last update. Called from state-change listener."""
        today = dt_util.now().strftime("%Y-%m-%d")
        if self._last_reset_date != today:
            self._day_energy_data = {}
            self._last_reset_date = today
            self._last_power_update = {}
        last = self._last_power_update.get(entity_id)
        now = dt_util.utcnow()
        if last is not None:
            elapsed = (now - last["time"]).total_seconds()
            if 0 < elapsed < 86400:  # Sanity: max 24h
                await self.async_add_energy_reading(
                    entity_id, last["watts"], elapsed_seconds=elapsed
                )
        self._last_power_update[entity_id] = {"watts": new_watts, "time": now}

    # Event count tracking (warnings and shutoffs) - per current date only
    def _ensure_event_counts_for_today(self) -> None:
        """Reset event counts if date has changed (new day)."""
        today = dt_util.now().strftime("%Y-%m-%d")
        if self._event_counts_reset_date != today:
            self._event_counts = {
                "total_warnings": 0,
                "total_shutoffs": 0,
                "room_warnings": {},
                "room_shutoffs": {},
            }
            self._event_counts_reset_date = today

    async def _async_load_event_counts(self) -> None:
        """Load event counts (warnings and shutoffs). Reset if new day."""
        counts_path = self.hass.config.path("smart_dashboards_event_counts.json")
        try:
            data = await self.hass.async_add_executor_job(
                _load_json_file, counts_path
            )
            if data is not None:
                self._event_counts_reset_date = data.get("last_reset_date")
                self._event_counts = {
                    "total_warnings": data.get("total_warnings", 0),
                    "total_shutoffs": data.get("total_shutoffs", 0),
                    "room_warnings": data.get("room_warnings", {}),
                    "room_shutoffs": data.get("room_shutoffs", {}),
                }
        except (json.JSONDecodeError, IOError):
            pass
        self._ensure_event_counts_for_today()

    async def _async_save_event_counts(self) -> None:
        """Save event counts with current date."""
        counts_path = self.hass.config.path("smart_dashboards_event_counts.json")
        payload = {
            "last_reset_date": self._event_counts_reset_date or dt_util.now().strftime("%Y-%m-%d"),
            "total_warnings": self._event_counts.get("total_warnings", 0),
            "total_shutoffs": self._event_counts.get("total_shutoffs", 0),
            "room_warnings": self._event_counts.get("room_warnings", {}),
            "room_shutoffs": self._event_counts.get("room_shutoffs", {}),
        }
        try:
            await self.hass.async_add_executor_job(
                _write_json_file, counts_path, payload
            )
        except IOError as err:
            _LOGGER.error("Error saving event counts: %s", err)

    async def async_increment_warning(self, room_id: str) -> None:
        """Increment warning count for a room and total (today only)."""
        self._ensure_event_counts_for_today()
        self._event_counts["total_warnings"] = self._event_counts.get("total_warnings", 0) + 1
        if room_id not in self._event_counts["room_warnings"]:
            self._event_counts["room_warnings"][room_id] = 0
        self._event_counts["room_warnings"][room_id] += 1
        await self._async_save_event_counts()

    async def async_increment_shutoff(self, room_id: str) -> None:
        """Increment shutoff count for a room and total (today only)."""
        self._ensure_event_counts_for_today()
        self._event_counts["total_shutoffs"] = self._event_counts.get("total_shutoffs", 0) + 1
        if room_id not in self._event_counts["room_shutoffs"]:
            self._event_counts["room_shutoffs"][room_id] = 0
        self._event_counts["room_shutoffs"][room_id] += 1
        await self._async_save_event_counts()

    def get_event_counts(self) -> dict[str, Any]:
        """Get event counts for current date only."""
        self._ensure_event_counts_for_today()
        return self._event_counts.copy()

    # Daily totals history (end-of-day snapshots for 30-day graphs)
    async def _async_load_daily_totals(self) -> None:
        """Load daily totals history from file."""
        path = self.hass.config.path("smart_dashboards_daily_totals.json")
        try:
            data = await self.hass.async_add_executor_job(_load_json_file, path)
            self._daily_totals = data.get("days", {}) if data else {}
        except (json.JSONDecodeError, IOError):
            self._daily_totals = {}

    async def _async_save_daily_totals(self) -> None:
        """Save daily totals history (keep last 45 days)."""
        dates_sorted = sorted(self._daily_totals.keys(), reverse=True)
        if len(dates_sorted) > 45:
            for d in dates_sorted[45:]:
                del self._daily_totals[d]
        path = self.hass.config.path("smart_dashboards_daily_totals.json")
        try:
            await self.hass.async_add_executor_job(
                _write_json_file, path, {"days": self._daily_totals}
            )
        except IOError as err:
            _LOGGER.error("Error saving daily totals: %s", err)

    async def async_snapshot_day_and_reset_if_rolled_over(self) -> None:
        """If date rolled over, snapshot previous day's totals to history, then reset."""
        today = dt_util.now().strftime("%Y-%m-%d")
        old_date = self._last_reset_date or self._event_counts_reset_date
        if not old_date or old_date == today:
            return

        rooms_data = {}
        energy_config = self.energy_config
        for room in energy_config.get("rooms", []):
            room_id = room.get("id", room["name"].lower().replace(" ", "_"))
            room_wh = 0.0
            for outlet in room.get("outlets", []):
                if outlet.get("type") == "light":
                    key = f"light_{room_id}_{(outlet.get('name') or 'light').lower().replace(' ', '_')}"
                    room_wh += self._day_energy_data.get(key, {}).get("energy", 0.0)
                else:
                    for e in (outlet.get("plug1_entity"), outlet.get("plug2_entity")):
                        if e:
                            room_wh += self._day_energy_data.get(e, {}).get("energy", 0.0)

            rooms_data[room_id] = {
                "wh": round(room_wh, 2),
                "warnings": self._event_counts.get("room_warnings", {}).get(room_id, 0),
                "shutoffs": self._event_counts.get("room_shutoffs", {}).get(room_id, 0),
            }

        total_wh = sum(r["wh"] for r in rooms_data.values())
        self._daily_totals[old_date] = {
            "total_wh": round(total_wh, 2),
            "total_warnings": self._event_counts.get("total_warnings", 0),
            "total_shutoffs": self._event_counts.get("total_shutoffs", 0),
            "rooms": rooms_data,
        }
        await self._async_save_daily_totals()

        self._day_energy_data = {}
        self._last_reset_date = today
        self._last_power_update = {}
        self._event_counts = {
            "total_warnings": 0,
            "total_shutoffs": 0,
            "room_warnings": {},
            "room_shutoffs": {},
        }
        self._event_counts_reset_date = today
        await self._async_save_energy_tracking()
        await self._async_save_event_counts()

    def _build_today_totals(self) -> dict[str, Any]:
        """Build today's running totals from current data."""
        self._ensure_event_counts_for_today()
        rooms_data = {}
        for room in self.energy_config.get("rooms", []):
            rid = room.get("id", room["name"].lower().replace(" ", "_"))
            room_wh = 0.0
            for outlet in room.get("outlets", []):
                if outlet.get("type") == "light":
                    key = f"light_{rid}_{(outlet.get('name') or 'light').lower().replace(' ', '_')}"
                    room_wh += self._day_energy_data.get(key, {}).get("energy", 0.0)
                else:
                    for e in (outlet.get("plug1_entity"), outlet.get("plug2_entity")):
                        if e:
                            room_wh += self._day_energy_data.get(e, {}).get("energy", 0.0)
            rooms_data[rid] = {
                "wh": round(room_wh, 2),
                "warnings": self._event_counts.get("room_warnings", {}).get(rid, 0),
                "shutoffs": self._event_counts.get("room_shutoffs", {}).get(rid, 0),
            }
        total_wh = sum(r["wh"] for r in rooms_data.values())
        return {
            "total_wh": round(total_wh, 2),
            "total_warnings": self._event_counts.get("total_warnings", 0),
            "total_shutoffs": self._event_counts.get("total_shutoffs", 0),
            "rooms": rooms_data,
        }

    def get_daily_history(self, days: int = 30, include_today: bool = True) -> dict[str, Any]:
        """Get daily totals for graphs. Only returns dates that have data, from earliest to latest.
        Chart grows over time until full range is available (no leading blank sections)."""
        from datetime import timedelta
        today = dt_util.now().strftime("%Y-%m-%d")
        all_room_ids = {
            r.get("id", r["name"].lower().replace(" ", "_"))
            for r in self.energy_config.get("rooms", [])
        }
        result = {"dates": [], "total_wh": [], "total_warnings": [], "total_shutoffs": [], "rooms": {}}
        for rid in all_room_ids:
            result["rooms"][rid] = {"wh": [], "warnings": [], "shutoffs": []}

        # Collect only dates that have data (in _daily_totals or today)
        candidates = []
        for i in range(days):
            d = (dt_util.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            if d == today and include_today:
                candidates.append((d, self._build_today_totals()))
            elif d in self._daily_totals:
                candidates.append((d, self._daily_totals[d]))

        # Sort chronologically (oldest first) and limit to days
        candidates.sort(key=lambda x: x[0])
        for d, row in candidates:
            result["dates"].append(d)
            result["total_wh"].append(row.get("total_wh", 0))
            result["total_warnings"].append(row.get("total_warnings", 0))
            result["total_shutoffs"].append(row.get("total_shutoffs", 0))
            row_rooms = row.get("rooms") or {}
            for rid in all_room_ids:
                rdata = row_rooms.get(rid, {})
                result["rooms"][rid]["wh"].append(rdata.get("wh", 0))
                result["rooms"][rid]["warnings"].append(rdata.get("warnings", 0))
                result["rooms"][rid]["shutoffs"].append(rdata.get("shutoffs", 0))

        return result

    # Billing history (for new-cycle alerts)
    async def _async_load_billing_history(self) -> None:
        """Load billing history from file."""
        path = self.hass.config.path("smart_dashboards_billing_history.json")
        try:
            data = await self.hass.async_add_executor_job(_load_json_file, path)
            if data:
                self._billing_history = {
                    "cycles": data.get("cycles", []),
                    "last_billing_start": data.get("last_billing_start", ""),
                    "last_billing_end": data.get("last_billing_end", ""),
                }
        except (json.JSONDecodeError, IOError):
            pass

    async def _async_save_billing_history(self) -> None:
        """Save billing history to file."""
        path = self.hass.config.path("smart_dashboards_billing_history.json")
        try:
            await self.hass.async_add_executor_job(
                _write_json_file, path, self._billing_history
            )
        except IOError as err:
            _LOGGER.error("Error saving billing history: %s", err)

    def _parse_date_sensor(self, entity_id: str) -> str | None:
        """Read sensor state and parse date. Accepts YYYY-MM-DD, MM/DD/YYYY, MM-DD-YYYY.
        Returns normalized YYYY-MM-DD or None."""
        if not entity_id or not entity_id.strip():
            return None
        state = self.hass.states.get(entity_id.strip())
        if not state or state.state in ("unknown", "unavailable", ""):
            return None
        val = str(state.state).strip()
        # YYYY-MM-DD
        m = re.match(r"(\d{4})-(\d{2})-(\d{2})", val)
        if m:
            return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        # MM/DD/YYYY or MM-DD-YYYY (first<=12=month, second=day) or DD/MM when first>12
        m = re.match(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", val)
        if m:
            a, b, y = int(m.group(1)), int(m.group(2)), m.group(3)
            if a > 12 and b <= 12:
                mo, d = b, a  # DD/MM
            else:
                mo, d = a, b  # MM/DD
            return f"{y}-{str(mo).zfill(2)}-{str(d).zfill(2)}"
        return None

    def get_billing_date_range(self) -> tuple[str | None, str | None]:
        """Read billing sensors and return (start, end) as YYYY-MM-DD or (None, None)."""
        stats = self.energy_config.get("statistics_settings", {})
        start_ent = stats.get("billing_start_sensor", "").strip()
        end_ent = stats.get("billing_end_sensor", "").strip()
        if not start_ent or not end_ent:
            return (None, None)
        start = self._parse_date_sensor(start_ent)
        end = self._parse_date_sensor(end_ent)
        return (start, end)

    def get_statistics_date_range(
        self, date_start: str | None = None, date_end: str | None = None
    ) -> tuple[str | None, str | None, bool]:
        """Resolve final date range. Returns (start, end, is_narrowed).
        Applies user narrow range within billing; clamps to available daily totals."""
        stats = self.energy_config.get("statistics_settings", {})
        billing_start, billing_end = self.get_billing_date_range()
        user_start = (stats.get("date_range_start") or "").strip() or date_start
        user_end = (stats.get("date_range_end") or "").strip() or date_end

        if billing_start and billing_end:
            base_start = billing_start
            base_end = billing_end
        else:
            available = sorted(self._daily_totals.keys())
            if not available:
                return (None, None, False)
            base_start = available[0]
            base_end = available[-1]

        start = base_start
        end = base_end
        if user_start and user_start >= base_start and (not user_end or user_start <= user_end):
            start = user_start
        if user_end and user_end <= base_end and (not user_start or user_end >= user_start):
            end = user_end

        available = set(self._daily_totals.keys())
        if start and start not in available:
            after = [d for d in available if d >= start]
            start = min(after) if after else start
        if end and end not in available:
            before = [d for d in available if d <= end]
            end = max(before) if before else end

        is_narrowed = (user_start or user_end) and (start != base_start or end != base_end)
        return (start, end, is_narrowed)

    async def record_billing_cycle_if_changed(self, start: str, end: str) -> bool:
        """If billing dates differ from last known, append to cycles and save. Returns True if changed."""
        if not start or not end:
            return False
        last_start = self._billing_history.get("last_billing_start", "")
        last_end = self._billing_history.get("last_billing_end", "")
        if start == last_start and end == last_end:
            return False
        now_str = dt_util.now().isoformat()
        self._billing_history["cycles"].append({
            "start": start,
            "end": end,
            "detected_at": now_str,
        })
        if len(self._billing_history["cycles"]) > 60:
            self._billing_history["cycles"] = self._billing_history["cycles"][-60:]
        self._billing_history["last_billing_start"] = start
        self._billing_history["last_billing_end"] = end
        await self._async_save_billing_history()
        return True

    def get_all_outlets(self) -> list[dict[str, Any]]:
        """Get all outlets from all rooms with their identifiers."""
        outlets = []
        for room in self.energy_config.get("rooms", []):
            room_id = room.get("id", room["name"].lower().replace(" ", "_"))
            for outlet in room.get("outlets", []):
                outlet_id = f"{room_id}_{outlet.get('name', 'outlet').lower().replace(' ', '_')}"
                outlets.append({
                    "id": outlet_id,
                    "room_id": room_id,
                    "room_name": room["name"],
                    "outlet_name": outlet.get("name", "Outlet"),
                    "plug1_switch": outlet.get("plug1_switch"),
                    "plug2_switch": outlet.get("plug2_switch"),
                    "plug1_entity": outlet.get("plug1_entity"),
                    "plug2_entity": outlet.get("plug2_entity"),
                })
        return outlets

    def get_outlets_for_breaker(self, breaker_id: str) -> list[dict[str, Any]]:
        """Get all outlets assigned to a breaker line."""
        breaker_lines = self.energy_config.get("breaker_lines", [])
        breaker = next((b for b in breaker_lines if b.get("id") == breaker_id), None)
        if not breaker:
            return []
        
        outlet_ids = breaker.get("outlet_ids", [])
        all_outlets = self.get_all_outlets()
        return [outlet for outlet in all_outlets if outlet["id"] in outlet_ids]
