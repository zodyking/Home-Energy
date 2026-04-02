"""Configuration manager for Smart Dashboards."""
from __future__ import annotations

import json
import logging
import math
import os
import re
from copy import deepcopy
from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import CONFIG_FILE, DEFAULT_CONFIG, DOMAIN, DEFAULT_TTS_VOLUME

_LOGGER = logging.getLogger(__name__)


def _safe_int(val: Any, default: int) -> int:
    """Parse int safely; return default for None, empty string, or invalid."""
    if val is None or val == "":
        return default
    try:
        return int(val) if isinstance(val, (int, float)) else int(str(val).strip())
    except (ValueError, TypeError):
        return default


def _safe_float(val: Any, default: float) -> float:
    """Parse float safely; return default for None, empty string, or invalid."""
    if val is None or val == "":
        return default
    try:
        return float(val) if isinstance(val, (int, float)) else float(str(val).strip())
    except (ValueError, TypeError):
        return default


def _coerce_bool(val: Any, default: bool = True) -> bool:
    """Coerce a value to bool; handles string 'false'/'true'/etc. safely.

    - bool(val) is True for non-empty strings like "false" in Python
    - This helper treats "false", "no", "0", "" as False explicitly
    """
    if val is None:
        return default
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return bool(val)
    if isinstance(val, str):
        lower = val.strip().lower()
        if lower in ("false", "no", "0", "off", ""):
            return False
        if lower in ("true", "yes", "1", "on"):
            return True
        return default
    return bool(val)


_ROOM_KWH_INTERVALS_DEFAULT: list[int] = [5, 10, 15, 20]


def _normalize_room_kwh_intervals(raw: Any) -> list[int | float]:
    """Exactly four strictly increasing positive thresholds; else default (matches energy-panel.js)."""
    nums: list[float] = []
    if isinstance(raw, list):
        items: list[Any] = list(raw)
    elif isinstance(raw, str):
        items = [p.strip() for p in raw.split(",") if p.strip()]
    else:
        return list(_ROOM_KWH_INTERVALS_DEFAULT)

    for x in items:
        try:
            n = float(x)
        except (TypeError, ValueError):
            continue
        if math.isfinite(n) and n > 0:
            nums.append(n)

    if len(nums) != 4:
        return list(_ROOM_KWH_INTERVALS_DEFAULT)

    sorted_nums = sorted(nums)
    if len(set(sorted_nums)) != 4:
        return list(_ROOM_KWH_INTERVALS_DEFAULT)
    for i in range(1, 4):
        if sorted_nums[i] <= sorted_nums[i - 1]:
            return list(_ROOM_KWH_INTERVALS_DEFAULT)

    out: list[int | float] = []
    for n in sorted_nums:
        out.append(int(n) if n == int(n) else n)
    return out


def _room_kwh_alert_threshold_key(x: Any) -> float:
    """Stable float key for kwh_alerts_sent (matches filter output rounding)."""
    return round(float(x), 4)


def _normalize_budget_boost_weekdays(raw: Any) -> list[int]:
    """Unique weekdays Monday=0..Sunday=6."""
    if not isinstance(raw, list):
        return []
    out: list[int] = []
    for x in raw:
        try:
            n = int(x)
            if 0 <= n <= 6 and n not in out:
                out.append(n)
        except (TypeError, ValueError):
            continue
    out.sort()
    return out


def _validate_budget_boost_announce_time(raw: Any, default: str) -> str:
    s = (str(raw).strip() if raw is not None else "") or default
    m = re.match(r"^(\d{1,2}):(\d{2})$", s)
    if not m:
        return default
    h, mi = int(m.group(1)), int(m.group(2))
    if not (0 <= h <= 23 and 0 <= mi <= 59):
        return default
    return f"{h:02d}:{mi:02d}"


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


def _power_source_for_light_vent(outlet: dict[str, Any]) -> tuple[str, str | None]:
    """configured = static watts; sensor = power_sensor_entity (sensor.* or switch.*)."""
    ps = str(outlet.get("power_source") or "configured").strip().lower()
    if ps not in ("configured", "sensor"):
        ps = "configured"
    pse = str(outlet.get("power_sensor_entity") or "").strip()
    if not pse.startswith(("sensor.", "switch.")):
        pse = ""
    if ps == "sensor" and not pse:
        ps = "configured"
    return ps, (pse if ps == "sensor" else None)


def _normalize_presence_person_entity(val: Any) -> str | None:
    s = str(val or "").strip()
    return s if s.startswith("person.") else None


def _normalize_presence_zone_entities(raw: Any) -> list[str]:
    if isinstance(raw, str) and raw.strip():
        raw = [raw.strip()]
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for z in raw:
        zs = str(z or "").strip()
        if zs.startswith("zone."):
            out.append(zs)
    seen: set[str] = set()
    uniq: list[str] = []
    for z in out:
        if z not in seen:
            seen.add(z)
            uniq.append(z)
    return uniq[:20]


_ROOM_ICON_PATTERN = re.compile(r"^mdi:[a-z0-9-]+$")


def _normalize_room_icon(val: Any) -> str | None:
    """MDI id for room card icon; invalid or empty → None (UI shows mdi:home)."""
    s = str(val or "").strip()
    if not s or len(s) > 80:
        return None
    if not _ROOM_ICON_PATTERN.match(s):
        return None
    return s


def _normalize_outlet_type(val: Any) -> str:
    """Legacy ceiling_vent_fan → vent."""
    t = str(val or "outlet").strip()
    if t == "ceiling_vent_fan":
        return "vent"
    return t if t else "outlet"


def _normalize_binary_sensor_entity(val: Any) -> str | None:
    s = str(val or "").strip()
    return s if s.startswith("binary_sensor.") else None


def vent_like_energy_tracking_key(room_id: str, outlet: dict) -> str:
    """Synthetic key for vent / wall heater static-watts energy when switch is on."""
    name = (outlet.get("name") or "device").lower().replace(" ", "_")
    if outlet.get("type") == "wall_heater":
        return f"wall_heater_{room_id}_{name}"
    return f"ceiling_vent_{room_id}_{name}"


def _event_log_dedupe_key(e: dict[str, Any]) -> tuple[Any, ...]:
    """Stable key to dedupe same logical event across rolling log and archive."""
    return (
        str(e.get("ts") or ""),
        str(e.get("room_id") or ""),
        str(e.get("type") or ""),
        str(e.get("tts_message") or ""),
    )


class ConfigManager:
    """Manage Smart Dashboards configuration stored in JSON file."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the config manager."""
        self.hass = hass
        self._config: dict[str, Any] = deepcopy(DEFAULT_CONFIG)
        # Store data in HA's config directory (survives integration updates)
        self._data_dir = hass.config.path("smart_dashboards_data")
        self._config_path = self._data_path("config.json")
        self._day_energy_data: dict[str, dict[str, float]] = {}
        self._last_reset_date: str | None = None
        self._event_counts_reset_date: str | None = None
        self._event_counts: dict[str, Any] = {
            "total_warnings": 0,
            "total_shutoffs": 0,
            "total_power_cycles": 0,
            "room_warnings": {},  # room_id -> count (today only)
            "room_shutoffs": {},  # room_id -> count (today only)
            "room_power_cycles": {},  # room_id -> enforcement phase-2 cycle initiations (today)
        }
        self._daily_totals: dict[str, Any] = {}
        self._billing_history: dict[str, Any] = {
            "cycles": [],
            "last_billing_start": "",
            "last_billing_end": "",
        }
        self._last_power_update: dict[str, dict] = {}  # entity_id -> {watts, time}
        # Intraday history: minute-by-minute power readings for 24-hour charts
        # Structure: {entity_id: [(timestamp_minute, watts), ...]} - keeps last 1440 entries (24h)
        self._intraday_history: dict[str, list] = {}

        # Power enforcement tracking
        # Structure: {room_id: {"warnings": [(timestamp, watts), ...], "phase": 0|1|2, "volume_offset": 0, "last_phase_change": timestamp, "kwh_alerts_sent": [5, 10, ...]}}
        self._enforcement_state: dict[str, dict] = {}
        self._home_kwh_alert_sent: bool = False  # Whether we've sent the home kWh alert today
        self._enforcement_reset_date: str | None = None

        # Event log: 24h warnings/shutoffs with TTS success/fail (for dashboard log modal)
        self._event_log: list[dict[str, Any]] = []
        self._event_log_max_entries = 500
        # Per-calendar-day archive for billing/statistics (full detail, longer retention)
        self._event_archive_days: dict[str, list[dict[str, Any]]] = {}
        # Statistics cache: pre-computed statistics for instant page load
        self._statistics_cache_data: dict[str, Any] = {}

    def _ensure_data_dir(self) -> str:
        """Ensure data directory exists and return its path."""
        if not os.path.exists(self._data_dir):
            os.makedirs(self._data_dir, exist_ok=True)
        return self._data_dir

    def _data_path(self, filename: str) -> str:
        """Return full path for a data file in the integration data directory."""
        self._ensure_data_dir()
        return os.path.join(self._data_dir, filename)

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

    @property
    def statistics_cache_data(self) -> dict[str, Any]:
        """Return cached statistics data (read-only)."""
        return self._statistics_cache_data

    def is_room_enforcement_enabled(self, room_id: str) -> bool:
        """Return True if power enforcement is enabled and this room is in rooms_enabled."""
        pe = self.energy_config.get("power_enforcement", {})
        return bool(pe.get("enabled", False)) and room_id in pe.get("rooms_enabled", [])

    @staticmethod
    def _is_budget_boost_day(now, tts_settings: dict) -> bool:
        """True when today's weekday matches budget boost schedule and multiplier > 1."""
        if not tts_settings.get("budget_boost_enabled"):
            return False
        mult = float(tts_settings.get("budget_boost_multiplier") or 1)
        if mult <= 1:
            return False
        days = tts_settings.get("budget_boost_weekdays") or []
        if not days:
            return False
        try:
            wk = now.weekday()
            for d in days:
                try:
                    if int(d) == wk:
                        return True
                except (TypeError, ValueError):
                    continue
            return False
        except (TypeError, AttributeError):
            return False

    @classmethod
    def filter_room_kwh_intervals_for_alerts(
        cls,
        raw_intervals: Any,
        base_kwh: float,
        now,
        tts_settings: dict | None,
        *,
        use_room_budget_boost: bool = True,
    ) -> list[float]:
        """Intervals used for room kWh TTS; matches energy-panel (budget replaces t0 when base > 0)."""
        t_norm = _normalize_room_kwh_intervals(
            raw_intervals if isinstance(raw_intervals, list) and len(raw_intervals) else []
        )
        t0, t1, t2, t3 = (float(t_norm[i]) for i in range(4))
        base = max(0.0, float(base_kwh or 0))
        eff = float(
            cls.effective_kwh_budget_for_moment(
                base, now, tts_settings or {}, use_room_boost=use_room_budget_boost
            )
        )
        boost = base > 1e-12 and eff > base + 1e-9
        if base > 0:
            milestones = sorted(
                {
                    _room_kwh_alert_threshold_key(eff),
                    _room_kwh_alert_threshold_key(t1),
                    _room_kwh_alert_threshold_key(t2),
                    _room_kwh_alert_threshold_key(t3),
                }
            )
            if boost:
                out = [v for v in milestones if v >= eff - 1e-9]
            else:
                out = [v for v in milestones if v >= base - 1e-9]
            return out
        milestones = [_room_kwh_alert_threshold_key(x) for x in (t0, t1, t2, t3)]
        if boost:
            return [v for v in milestones if v >= eff - 1e-9]
        return milestones

    @classmethod
    def effective_kwh_budget_for_moment(
        cls,
        base_kwh: float,
        now,
        tts_settings: dict | None,
        *,
        use_room_boost: bool = True,
    ) -> float:
        """Daily kWh budget after boost multiplier (matches energy_monitor logic).

        If use_room_boost is False, this room always uses base kWh (ignores global boost).
        """
        base = float(base_kwh or 0)
        if base <= 0:
            return base
        if not use_room_boost:
            return base
        tts = tts_settings or {}
        if not cls._is_budget_boost_day(now, tts):
            return base
        mult = float(tts.get("budget_boost_multiplier") or 2)
        mult = max(1.0, min(5.0, mult))
        return round(base * mult, 4)

    def get_room_kwh_budgets(self, room_id: str) -> tuple[float, float]:
        """Return (base_kwh_budget, effective_kwh_budget) for local now."""
        now = dt_util.now()
        base = 0.0
        use_boost = True
        for r in self.energy_config.get("rooms", []):
            rid = r.get("id", r["name"].lower().replace(" ", "_"))
            if rid == room_id:
                base = float(r.get("kwh_budget", 5) or 0)
                use_boost = r.get("kwh_budget_use_boost", True) is not False
                break
        tts = self.energy_config.get("tts_settings") or {}
        eff = self.effective_kwh_budget_for_moment(
            base, now, tts, use_room_boost=use_boost
        )
        return (base, eff)

    async def _migrate_data_files(self) -> None:
        """Move data files from old locations to smart_dashboards_data directory.
        
        Checks two old locations:
        1. /config/smart_dashboards*.json (original location)
        2. /config/custom_components/smart_dashboards/data/*.json (v1.0.51-1.0.55 location - bad, gets overwritten)
        """
        import shutil
        migrations = [
            ("smart_dashboards.json", "config.json"),
            ("smart_dashboards_energy_tracking.json", "energy_tracking.json"),
            ("smart_dashboards_event_counts.json", "event_counts.json"),
            ("smart_dashboards_event_log.json", "event_log.json"),
            ("smart_dashboards_event_archive.json", "event_archive.json"),
            ("smart_dashboards_daily_totals.json", "daily_totals.json"),
            ("smart_dashboards_statistics_cache.json", "statistics_cache.json"),
            ("smart_dashboards_billing_history.json", "billing_history.json"),
            ("smart_dashboards_enforcement_state.json", "enforcement_state.json"),
            ("smart_dashboards_intraday_history.json", "intraday_history.json"),
            ("smart_dashboards_budget_boost_slots.json", "budget_boost_slots.json"),
        ]
        # Old integration data folder (v1.0.51-1.0.55, inside custom_components - gets overwritten!)
        old_integration_data = os.path.join(os.path.dirname(__file__), "data")
        
        self._ensure_data_dir()
        for old_name, new_name in migrations:
            new_path = self._data_path(new_name)
            if os.path.exists(new_path):
                continue  # Already migrated
            
            # Try original config root location first
            old_path = self.hass.config.path(old_name)
            if os.path.exists(old_path):
                try:
                    await self.hass.async_add_executor_job(shutil.move, old_path, new_path)
                    _LOGGER.info("Migrated %s to smart_dashboards_data/%s", old_name, new_name)
                    continue
                except Exception as err:
                    _LOGGER.warning("Failed to migrate %s: %s", old_name, err)
            
            # Try old integration data folder (v1.0.51-1.0.55)
            old_integration_path = os.path.join(old_integration_data, new_name)
            if os.path.exists(old_integration_path):
                try:
                    await self.hass.async_add_executor_job(shutil.move, old_integration_path, new_path)
                    _LOGGER.info("Migrated data/%s to smart_dashboards_data/%s", new_name, new_name)
                except Exception as err:
                    _LOGGER.warning("Failed to migrate data/%s: %s", new_name, err)

    async def async_load(self) -> None:
        """Load configuration from file."""
        # Migrate old data files from config root to integration data directory
        await self._migrate_data_files()

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
        # Load event log
        await self._async_load_event_log()
        await self._async_load_event_archive()
        # Load daily totals history
        await self._async_load_daily_totals()
        # Load billing history
        await self._async_load_billing_history()
        # Load enforcement state
        await self._async_load_enforcement_state()
        # Load intraday history
        await self._async_load_intraday_history()
        # Load statistics cache for instant page load
        await self._async_load_statistics_cache()

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
            if "power_enforcement" in energy:
                pe_loaded = energy["power_enforcement"]
                pe_result = result["energy"]["power_enforcement"]
                for k in list(pe_result.keys()) + list(pe_loaded.keys()):
                    if k in pe_loaded and pe_loaded[k] is not None:
                        pe_result[k] = pe_loaded[k]
            if "statistics_settings" in energy:
                ss_result = result["energy"]["statistics_settings"]
                for k, v in energy["statistics_settings"].items():
                    if k not in ss_result:
                        continue
                    if k == "statistics_refresh_seconds":
                        if v is not None and str(v).strip() != "":
                            try:
                                ss_result[k] = int(float(str(v).strip()))
                            except (ValueError, TypeError):
                                pass
                    elif v:
                        ss_result[k] = str(v).strip()
            if "efficiency_settings" in energy:
                es_result = result["energy"]["efficiency_settings"]
                ev = energy["efficiency_settings"]
                if isinstance(ev, dict):
                    for k in list(es_result.keys()):
                        if k not in ev:
                            continue
                        val = ev[k]
                        if val is None:
                            continue
                        if isinstance(es_result[k], bool):
                            es_result[k] = _coerce_bool(val, es_result[k])
                        elif isinstance(es_result[k], (int, float)) and not isinstance(
                            es_result[k], bool
                        ):
                            try:
                                if isinstance(es_result[k], int):
                                    es_result[k] = int(float(val))
                                else:
                                    es_result[k] = float(val)
                            except (TypeError, ValueError):
                                pass
                        elif isinstance(es_result[k], str):
                            es_result[k] = str(val).strip()

        return result

    async def async_update_energy(self, energy_config: dict[str, Any]) -> None:
        """Update energy configuration."""
        existing = self._config.get("energy", {})
        default_energy = DEFAULT_CONFIG["energy"]
        merged = dict(energy_config)
        # Preserve existing values when incoming config omits or sends empty structured fields
        for key in (
            "power_enforcement",
            "statistics_settings",
            "efficiency_settings",
            "breaker_lines",
            "breaker_panel_size",
        ):
            val = merged.get(key)
            if key not in merged:
                merged[key] = existing.get(key, default_energy.get(key))
            elif isinstance(val, (list, dict)) and len(val or []) == 0:
                merged[key] = existing.get(key, default_energy.get(key))
        self._config["energy"] = self._validate_energy_config(merged)
        await self.async_prune_kwh_alerts_sent_for_current_config()
        await self.async_save()
        monitor = self.hass.data.get(DOMAIN, {}).get("energy_monitor")
        if monitor is not None and hasattr(monitor, "refresh_presence_listeners"):
            monitor.refresh_presence_listeners()

    async def async_prune_kwh_alerts_sent_for_current_config(self) -> None:
        """Drop kwh_alerts_sent entries that are no longer eligible tiers after config change."""
        self._ensure_enforcement_state_for_today()
        now = dt_util.now()
        tts = self.energy_config.get("tts_settings") or {}
        pe = self.energy_config.get("power_enforcement") or {}
        raw_iv = pe.get("room_kwh_intervals", [5, 10, 15, 20])
        norm_iv = _normalize_room_kwh_intervals(raw_iv)
        changed = False
        for room in self.energy_config.get("rooms", []):
            room_id = room.get("id", room["name"].lower().replace(" ", "_"))
            base_b = float(room.get("kwh_budget", 5) or 0)
            use_boost = room.get("kwh_budget_use_boost", True) is not False
            allowed = {
                _room_kwh_alert_threshold_key(x)
                for x in self.filter_room_kwh_intervals_for_alerts(
                    norm_iv, base_b, now, tts, use_room_budget_boost=use_boost
                )
            }
            state = self.get_enforcement_state(room_id)
            sent = list(state.get("kwh_alerts_sent") or [])
            new_sent = [
                x for x in sent if _room_kwh_alert_threshold_key(x) in allowed
            ]
            if new_sent != sent:
                state["kwh_alerts_sent"] = new_sent
                changed = True
        if changed:
            await self._async_save_enforcement_state()

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
                    "kwh_budget": max(0, float(room.get("kwh_budget", 5))),
                    "kwh_budget_use_boost": (
                        room.get("kwh_budget_use_boost", True) is not False
                    ),
                    "volume": float(room.get("volume", 0.7)),
                    "responsive_light_warnings": bool(room.get("responsive_light_warnings", False)),
                    "responsive_light_color": _validate_rgb(room.get("responsive_light_color")),
                    "responsive_light_temp": max(2000, min(6500, _safe_int(room.get("responsive_light_temp"), 6500))),
                    "responsive_light_interval": max(0.1, min(10.0, _safe_float(room.get("responsive_light_interval"), 1.5))),
                    "presence_person_entity": _normalize_presence_person_entity(
                        room.get("presence_person_entity")
                    ),
                    "presence_zone_entities": _normalize_presence_zone_entities(
                        room.get("presence_zone_entities")
                    ),
                    "room_icon": _normalize_room_icon(room.get("room_icon")),
                    "outlets": [],
                }
                for outlet in room.get("outlets", []):
                    if isinstance(outlet, dict) and outlet.get("name"):
                        outlet_type = _normalize_outlet_type(outlet.get("type", "outlet"))
                        if outlet_type not in (
                            "outlet", "single_outlet", "stove", "microwave",
                            "minisplit", "light", "fridge", "vent", "wall_heater",
                        ):
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
                            item["stove_off_debounce_seconds"] = max(0, min(60, int(outlet.get("stove_off_debounce_seconds", 10))))
                            item["stove_on_debounce_seconds"] = max(0, min(60, int(outlet.get("stove_on_debounce_seconds", 0))))
                            item["cooking_time_minutes"] = int(outlet.get("cooking_time_minutes", 15))
                            item["final_warning_seconds"] = int(outlet.get("final_warning_seconds", 30))
                            item["timer_start_window_seconds"] = max(1, min(120, int(outlet.get("timer_start_window_seconds", 10))))
                            item["stove_timer_tts_interval_seconds"] = max(
                                0,
                                min(3600, int(outlet.get("stove_timer_tts_interval_seconds", 0))),
                            )
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
                            ps, pse = _power_source_for_light_vent(outlet)
                            item["power_source"] = ps
                            item["power_sensor_entity"] = pse
                        elif outlet_type == "minisplit":
                            item["plug2_entity"] = None
                            item["plug1_switch"] = outlet.get("plug1_switch")
                            item["plug2_switch"] = None
                            item["plug1_shutoff"] = int(outlet.get("plug1_shutoff", 0))
                            item["plug2_shutoff"] = 0
                            item["minisplit_enforcement_off_seconds"] = max(
                                30,
                                min(600, int(outlet.get("minisplit_enforcement_off_seconds", 60))),
                            )
                            item["minisplit_enforcement_min_watts"] = max(
                                0,
                                min(2000, int(outlet.get("minisplit_enforcement_min_watts", 0))),
                            )
                        elif outlet_type in ("single_outlet", "fridge"):
                            item["plug2_entity"] = None
                            item["plug1_switch"] = outlet.get("plug1_switch")
                            item["plug2_switch"] = None
                            item["plug1_shutoff"] = int(outlet.get("plug1_shutoff", 0))
                            item["plug2_shutoff"] = 0
                        elif outlet_type in ("vent", "wall_heater"):
                            item["plug1_entity"] = None
                            item["plug2_entity"] = None
                            item["plug1_switch"] = None
                            item["plug2_switch"] = None
                            item["plug1_shutoff"] = 0
                            item["plug2_shutoff"] = 0
                            item["switch_entity"] = outlet.get("switch_entity")
                            item["watts_when_on"] = max(0, int(outlet.get("watts_when_on", 0)))
                            ps, pse = _power_source_for_light_vent(outlet)
                            item["power_source"] = ps
                            item["power_sensor_entity"] = pse
                            if outlet_type == "vent":
                                item["vent_automation_enabled"] = bool(
                                    outlet.get("vent_automation_enabled")
                                )
                                item["vent_presence_entity"] = _normalize_binary_sensor_entity(
                                    outlet.get("vent_presence_entity")
                                )
                                item["vent_on_debounce_seconds"] = max(
                                    0, min(600, int(outlet.get("vent_on_debounce_seconds", 30)))
                                )
                                item["vent_off_after_no_presence_seconds"] = max(
                                    10,
                                    min(
                                        86400,
                                        int(outlet.get("vent_off_after_no_presence_seconds", 300)),
                                    ),
                                )
                            else:
                                item["heater_automation_enabled"] = bool(
                                    outlet.get("heater_automation_enabled")
                                )
                                te = str(outlet.get("heater_temperature_entity") or "").strip()
                                item["heater_temperature_entity"] = (
                                    te if te.startswith("sensor.") else None
                                )
                                item["heater_on_below_temperature"] = max(
                                    -60.0,
                                    min(160.0, float(outlet.get("heater_on_below_temperature", 65))),
                                )
                                hct = outlet.get("heater_comfort_temperature")
                                if hct is None or hct == "":
                                    item["heater_comfort_temperature"] = None
                                else:
                                    try:
                                        item["heater_comfort_temperature"] = max(
                                            -60.0,
                                            min(160.0, float(hct)),
                                        )
                                    except (TypeError, ValueError):
                                        item["heater_comfort_temperature"] = None
                                item["heater_stay_on_minutes"] = max(
                                    1, min(240, int(outlet.get("heater_stay_on_minutes", 5)))
                                )
                                item["heater_presence_optional_enabled"] = bool(
                                    outlet.get("heater_presence_optional_enabled")
                                )
                                item["heater_presence_turn_on_enabled"] = bool(
                                    outlet.get("heater_presence_turn_on_enabled")
                                )
                                item["heater_presence_entity"] = _normalize_binary_sensor_entity(
                                    outlet.get("heater_presence_entity")
                                )
                                item["heater_presence_cooldown_seconds"] = max(
                                    0,
                                    min(7200, int(outlet.get("heater_presence_cooldown_seconds", 60))),
                                )
                                # Smart heater optimization settings
                                item["heater_weather_entity"] = str(
                                    outlet.get("heater_weather_entity") or ""
                                ).strip()
                                item["heater_optimization_enabled"] = bool(
                                    outlet.get("heater_optimization_enabled", True)
                                )
                                item["heater_hysteresis_band"] = max(
                                    0.0,
                                    min(10.0, float(outlet.get("heater_hysteresis_band", 2.0) or 2.0)),
                                )
                                item["heater_duty_cycle_enabled"] = bool(
                                    outlet.get("heater_duty_cycle_enabled")
                                )
                                item["heater_duty_on_minutes"] = max(
                                    1,
                                    min(30, int(outlet.get("heater_duty_on_minutes", 5) or 5)),
                                )
                                item["heater_duty_off_minutes"] = max(
                                    1,
                                    min(15, int(outlet.get("heater_duty_off_minutes", 2) or 2)),
                                )
                                item["heater_duty_comfort_margin"] = max(
                                    0.0,
                                    min(10.0, float(outlet.get("heater_duty_comfort_margin", 1.0) or 1.0)),
                                )
                                item["heater_power_aware_enabled"] = bool(
                                    outlet.get("heater_power_aware_enabled")
                                )
                                item["heater_power_threshold_watts"] = max(
                                    100,
                                    min(5000, int(outlet.get("heater_power_threshold_watts", 500) or 500)),
                                )
                                item["heater_learning_enabled"] = bool(
                                    outlet.get("heater_learning_enabled", True)
                                )
                                item["heater_preheat_minutes"] = max(
                                    0,
                                    min(120, int(outlet.get("heater_preheat_minutes", 30) or 30)),
                                )
                                door_ent = str(outlet.get("heater_door_sensor_entity") or "").strip()
                                item["heater_door_sensor_entity"] = door_ent if door_ent.startswith("binary_sensor.") else None
                                window_ent = str(outlet.get("heater_window_sensor_entity") or "").strip()
                                item["heater_window_sensor_entity"] = window_ent if window_ent.startswith("binary_sensor.") else None
                        else:
                            item["plug2_entity"] = None
                            item["plug1_switch"] = None
                            item["plug2_switch"] = None
                            item["plug1_shutoff"] = 0
                            item["plug2_shutoff"] = 0
                        if outlet_type == "outlet":
                            item["presence_auto_off_plug1"] = bool(
                                outlet.get("presence_auto_off_plug1")
                            )
                            item["presence_auto_off_plug2"] = bool(
                                outlet.get("presence_auto_off_plug2")
                            )
                        else:
                            item["presence_auto_off"] = bool(outlet.get("presence_auto_off"))
                        validated_room["outlets"].append(item)
                validated["rooms"].append(validated_room)

        # Validate breaker panel size
        panel_size = _safe_int(config.get("breaker_panel_size"), 20)
        validated["breaker_panel_size"] = max(2, min(40, panel_size)) if panel_size and panel_size % 2 == 0 else 20

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
        _notification_title = str(
            tts.get("notification_title")
            or default_tts.get("notification_title")
            or "Home Energy"
        ).strip()
        if not _notification_title:
            _notification_title = "Home Energy"
        validated["tts_settings"] = {
            "language": tts.get("language", default_tts["language"]),
            "speed": _safe_float(tts.get("speed"), default_tts["speed"]),
            "volume": _safe_float(tts.get("volume"), default_tts["volume"]),
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
            "phase1_warn_msg": tts.get("phase1_warn_msg", default_tts.get("phase1_warn_msg", "")),
            "phase2_warn_msg": tts.get("phase2_warn_msg", default_tts.get("phase2_warn_msg", "")),
            "phase2_after_msg": tts.get("phase2_after_msg", default_tts.get("phase2_after_msg", "")),
            "minisplit_phase2_warn_msg": tts.get(
                "minisplit_phase2_warn_msg",
                default_tts.get("minisplit_phase2_warn_msg", ""),
            ),
            "minisplit_phase2_after_msg": tts.get(
                "minisplit_phase2_after_msg",
                default_tts.get("minisplit_phase2_after_msg", ""),
            ),
            "minisplit_phase2_restore_msg": tts.get(
                "minisplit_phase2_restore_msg",
                default_tts.get("minisplit_phase2_restore_msg", ""),
            ),
            "phase_reset_msg": tts.get("phase_reset_msg", default_tts.get("phase_reset_msg", "")),
            "room_kwh_warn_msg": tts.get("room_kwh_warn_msg", default_tts.get("room_kwh_warn_msg", "")),
            "home_kwh_warn_msg": tts.get("home_kwh_warn_msg", default_tts.get("home_kwh_warn_msg", "")),
            "budget_exceeded_msg": tts.get("budget_exceeded_msg", default_tts.get("budget_exceeded_msg", "")),
            "min_interval_seconds": max(1.0, min(60.0, _safe_float(tts.get("min_interval_seconds"), default_tts.get("min_interval_seconds", 3)))),
            "budget_boost_enabled": bool(tts.get("budget_boost_enabled", default_tts.get("budget_boost_enabled", False))),
            "budget_boost_multiplier": max(
                1.0,
                min(5.0, _safe_float(tts.get("budget_boost_multiplier"), default_tts.get("budget_boost_multiplier", 2.0))),
            ),
            "budget_boost_weekdays": _normalize_budget_boost_weekdays(
                tts.get("budget_boost_weekdays", default_tts.get("budget_boost_weekdays", []))
            ),
            "budget_boost_window_start": _validate_budget_boost_announce_time(
                tts.get("budget_boost_window_start")
                or tts.get("budget_boost_announce_time"),
                default_tts.get("budget_boost_window_start", "09:00"),
            ),
            "budget_boost_window_end": _validate_budget_boost_announce_time(
                tts.get("budget_boost_window_end"),
                default_tts.get("budget_boost_window_end", "21:00"),
            ),
            "budget_boost_repeat_minutes": max(
                15,
                min(720, _safe_int(tts.get("budget_boost_repeat_minutes"), default_tts.get("budget_boost_repeat_minutes", 120))),
            ),
            "budget_boost_minute_offset": max(
                0,
                min(59, _safe_int(tts.get("budget_boost_minute_offset"), default_tts.get("budget_boost_minute_offset", 0))),
            ),
            "budget_boost_announce_time": _validate_budget_boost_announce_time(
                tts.get("budget_boost_announce_time"),
                default_tts.get("budget_boost_announce_time", "09:00"),
            ),
            "budget_boost_announce_media_player": str(
                tts.get("budget_boost_announce_media_player", default_tts.get("budget_boost_announce_media_player", "")) or ""
            ).strip(),
            "tts_default_media_player": (
                str(tts.get("tts_default_media_player") or "").strip()
                or str(tts.get("budget_boost_announce_media_player") or "").strip()
                or str(default_tts.get("tts_default_media_player") or "").strip()
            ),
            "budget_boost_scheduled_msg": tts.get(
                "budget_boost_scheduled_msg",
                default_tts.get("budget_boost_scheduled_msg", ""),
            ),
            "phase1_warn_msg_boost_day": tts.get(
                "phase1_warn_msg_boost_day",
                default_tts.get("phase1_warn_msg_boost_day", ""),
            ),
            "stove_timer_progress_msg": tts.get(
                "stove_timer_progress_msg",
                default_tts.get("stove_timer_progress_msg", ""),
            ),
            "heater_automation_tts_enabled": bool(
                tts.get(
                    "heater_automation_tts_enabled",
                    default_tts.get("heater_automation_tts_enabled", False),
                )
            ),
            "vent_automation_tts_enabled": bool(
                tts.get(
                    "vent_automation_tts_enabled",
                    default_tts.get("vent_automation_tts_enabled", False),
                )
            ),
            "heater_automation_on_msg": tts.get(
                "heater_automation_on_msg",
                default_tts.get("heater_automation_on_msg", ""),
            ),
            "vent_automation_on_msg": tts.get(
                "vent_automation_on_msg",
                default_tts.get("vent_automation_on_msg", ""),
            ),
            "room_warn_tts_enabled": bool(
                tts.get(
                    "room_warn_tts_enabled",
                    default_tts.get("room_warn_tts_enabled", True),
                )
            ),
            "outlet_warn_tts_enabled": bool(
                tts.get(
                    "outlet_warn_tts_enabled",
                    default_tts.get("outlet_warn_tts_enabled", True),
                )
            ),
            "budget_exceeded_tts_enabled": bool(
                tts.get(
                    "budget_exceeded_tts_enabled",
                    default_tts.get("budget_exceeded_tts_enabled", True),
                )
            ),
            "budget_boost_scheduled_tts_enabled": bool(
                tts.get(
                    "budget_boost_scheduled_tts_enabled",
                    default_tts.get("budget_boost_scheduled_tts_enabled", True),
                )
            ),
            "phase1_warn_boost_day_tts_enabled": bool(
                tts.get(
                    "phase1_warn_boost_day_tts_enabled",
                    default_tts.get("phase1_warn_boost_day_tts_enabled", True),
                )
            ),
            "shutoff_tts_enabled": bool(
                tts.get(
                    "shutoff_tts_enabled",
                    default_tts.get("shutoff_tts_enabled", True),
                )
            ),
            "stove_on_tts_enabled": bool(
                tts.get(
                    "stove_on_tts_enabled",
                    default_tts.get("stove_on_tts_enabled", True),
                )
            ),
            "stove_off_tts_enabled": bool(
                tts.get(
                    "stove_off_tts_enabled",
                    default_tts.get("stove_off_tts_enabled", True),
                )
            ),
            "stove_timer_started_tts_enabled": bool(
                tts.get(
                    "stove_timer_started_tts_enabled",
                    default_tts.get("stove_timer_started_tts_enabled", True),
                )
            ),
            "stove_timer_progress_tts_enabled": bool(
                tts.get(
                    "stove_timer_progress_tts_enabled",
                    default_tts.get("stove_timer_progress_tts_enabled", True),
                )
            ),
            "stove_15min_warn_tts_enabled": bool(
                tts.get(
                    "stove_15min_warn_tts_enabled",
                    default_tts.get("stove_15min_warn_tts_enabled", True),
                )
            ),
            "stove_30sec_warn_tts_enabled": bool(
                tts.get(
                    "stove_30sec_warn_tts_enabled",
                    default_tts.get("stove_30sec_warn_tts_enabled", True),
                )
            ),
            "stove_auto_off_tts_enabled": bool(
                tts.get(
                    "stove_auto_off_tts_enabled",
                    default_tts.get("stove_auto_off_tts_enabled", True),
                )
            ),
            "phase1_warn_tts_enabled": bool(
                tts.get(
                    "phase1_warn_tts_enabled",
                    default_tts.get("phase1_warn_tts_enabled", True),
                )
            ),
            "phase2_warn_tts_enabled": bool(
                tts.get(
                    "phase2_warn_tts_enabled",
                    default_tts.get("phase2_warn_tts_enabled", True),
                )
            ),
            "phase2_after_tts_enabled": bool(
                tts.get(
                    "phase2_after_tts_enabled",
                    default_tts.get("phase2_after_tts_enabled", True),
                )
            ),
            "minisplit_phase2_warn_tts_enabled": bool(
                tts.get(
                    "minisplit_phase2_warn_tts_enabled",
                    default_tts.get("minisplit_phase2_warn_tts_enabled", True),
                )
            ),
            "minisplit_phase2_after_tts_enabled": bool(
                tts.get(
                    "minisplit_phase2_after_tts_enabled",
                    default_tts.get("minisplit_phase2_after_tts_enabled", True),
                )
            ),
            "minisplit_phase2_restore_tts_enabled": bool(
                tts.get(
                    "minisplit_phase2_restore_tts_enabled",
                    default_tts.get("minisplit_phase2_restore_tts_enabled", True),
                )
            ),
            "phase_reset_tts_enabled": bool(
                tts.get(
                    "phase_reset_tts_enabled",
                    default_tts.get("phase_reset_tts_enabled", True),
                )
            ),
            "room_kwh_warn_tts_enabled": bool(
                tts.get(
                    "room_kwh_warn_tts_enabled",
                    default_tts.get("room_kwh_warn_tts_enabled", True),
                )
            ),
            "home_kwh_warn_tts_enabled": bool(
                tts.get(
                    "home_kwh_warn_tts_enabled",
                    default_tts.get("home_kwh_warn_tts_enabled", True),
                )
            ),
            "notifications_enabled": bool(
                tts.get(
                    "notifications_enabled",
                    default_tts.get("notifications_enabled", False),
                )
            ),
            "notify_room_budget_hit": bool(
                tts.get(
                    "notify_room_budget_hit",
                    default_tts.get("notify_room_budget_hit", True),
                )
            ),
            "notify_enforcement_phase_change": bool(
                tts.get(
                    "notify_enforcement_phase_change",
                    default_tts.get("notify_enforcement_phase_change", True),
                )
            ),
            "notify_ac_auto_off": bool(
                tts.get(
                    "notify_ac_auto_off",
                    default_tts.get("notify_ac_auto_off", True),
                )
            ),
            "notify_ac_auto_on": bool(
                tts.get(
                    "notify_ac_auto_on",
                    default_tts.get("notify_ac_auto_on", True),
                )
            ),
            "notify_person_toggle": bool(
                tts.get(
                    "notify_person_toggle",
                    tts.get("notify_manual_toggle", default_tts.get("notify_person_toggle", True)),
                )
            ),
            "notify_integration_auto": bool(
                tts.get(
                    "notify_integration_auto",
                    default_tts.get("notify_integration_auto", True),
                )
            ),
            "notify_heater_auto": (
                _coerce_bool(tts.get("notify_heater_auto"), default=True)
                if "notify_heater_auto" in tts
                else _coerce_bool(tts.get("notify_integration_auto", True), default=True)
            ),
            "notify_vent_auto": (
                _coerce_bool(tts.get("notify_vent_auto"), default=True)
                if "notify_vent_auto" in tts
                else _coerce_bool(tts.get("notify_integration_auto", True), default=True)
            ),
            "notify_external_auto": bool(
                tts.get(
                    "notify_external_auto",
                    tts.get("notify_manual_toggle", default_tts.get("notify_external_auto", True)),
                )
            ),
            "notification_title": _notification_title,
            "notify_budget_hit_title": str(
                tts.get(
                    "notify_budget_hit_title",
                    default_tts.get("notify_budget_hit_title", ""),
                )
                or ""
            ),
            "notify_budget_hit_msg": str(
                tts.get(
                    "notify_budget_hit_msg",
                    default_tts.get("notify_budget_hit_msg", ""),
                )
                or ""
            ),
            "notify_enforcement_phase1_title": str(
                tts.get(
                    "notify_enforcement_phase1_title",
                    default_tts.get("notify_enforcement_phase1_title", ""),
                )
                or ""
            ),
            "notify_enforcement_phase1_msg": str(
                tts.get(
                    "notify_enforcement_phase1_msg",
                    default_tts.get("notify_enforcement_phase1_msg", ""),
                )
                or ""
            ),
            "notify_enforcement_phase2_title": str(
                tts.get(
                    "notify_enforcement_phase2_title",
                    default_tts.get("notify_enforcement_phase2_title", ""),
                )
                or ""
            ),
            "notify_enforcement_phase2_msg": str(
                tts.get(
                    "notify_enforcement_phase2_msg",
                    default_tts.get("notify_enforcement_phase2_msg", ""),
                )
                or ""
            ),
            "notify_ac_auto_off_title": str(
                tts.get(
                    "notify_ac_auto_off_title",
                    default_tts.get("notify_ac_auto_off_title", ""),
                )
                or ""
            ),
            "notify_ac_auto_off_msg": str(
                tts.get(
                    "notify_ac_auto_off_msg",
                    default_tts.get("notify_ac_auto_off_msg", ""),
                )
                or ""
            ),
            "notify_ac_auto_on_title": str(
                tts.get(
                    "notify_ac_auto_on_title",
                    default_tts.get("notify_ac_auto_on_title", ""),
                )
                or ""
            ),
            "notify_ac_auto_on_msg": str(
                tts.get(
                    "notify_ac_auto_on_msg",
                    default_tts.get("notify_ac_auto_on_msg", ""),
                )
                or ""
            ),
            "notify_toggle_title": str(
                tts.get(
                    "notify_toggle_title",
                    tts.get("notify_manual_toggle_title", default_tts.get("notify_toggle_title", "")),
                )
                or ""
            ),
            "notify_toggle_msg": str(
                tts.get(
                    "notify_toggle_msg",
                    tts.get("notify_manual_toggle_msg", default_tts.get("notify_toggle_msg", "")),
                )
                or ""
            ),
            "notify_heater_auto_on_title": str(
                tts.get(
                    "notify_heater_auto_on_title",
                    default_tts.get("notify_heater_auto_on_title", ""),
                )
                or ""
            ),
            "notify_heater_auto_on_msg": str(
                tts.get(
                    "notify_heater_auto_on_msg",
                    default_tts.get("notify_heater_auto_on_msg", ""),
                )
                or ""
            ),
            "notify_heater_auto_off_title": str(
                tts.get(
                    "notify_heater_auto_off_title",
                    default_tts.get("notify_heater_auto_off_title", ""),
                )
                or ""
            ),
            "notify_heater_auto_off_msg": str(
                tts.get(
                    "notify_heater_auto_off_msg",
                    default_tts.get("notify_heater_auto_off_msg", ""),
                )
                or ""
            ),
            "notify_vent_auto_on_title": str(
                tts.get(
                    "notify_vent_auto_on_title",
                    default_tts.get("notify_vent_auto_on_title", ""),
                )
                or ""
            ),
            "notify_vent_auto_on_msg": str(
                tts.get(
                    "notify_vent_auto_on_msg",
                    default_tts.get("notify_vent_auto_on_msg", ""),
                )
                or ""
            ),
            "notify_vent_auto_off_title": str(
                tts.get(
                    "notify_vent_auto_off_title",
                    default_tts.get("notify_vent_auto_off_title", ""),
                )
                or ""
            ),
            "notify_vent_auto_off_msg": str(
                tts.get(
                    "notify_vent_auto_off_msg",
                    default_tts.get("notify_vent_auto_off_msg", ""),
                )
                or ""
            ),
            "zone_health_check_enabled": _coerce_bool(
                tts.get(
                    "zone_health_check_enabled",
                    default_tts.get("zone_health_check_enabled", True),
                ),
                default_tts.get("zone_health_check_enabled", True),
            ),
            "zone_health_history_days": (
                lambda: (
                    # Prefer days if present; migrate from hours if not
                    max(1, min(3, int(tts.get("zone_health_history_days") or 0)))
                    if tts.get("zone_health_history_days")
                    else (
                        # Migrate hours -> days: 24->1, 48->2, 72->3, else 3
                        {24: 1, 48: 2, 72: 3, 96: 3}.get(
                            int(tts.get("zone_health_history_hours") or 0), 3
                        )
                        if tts.get("zone_health_history_hours")
                        else default_tts.get("zone_health_history_days", 3)
                    )
                )
            )(),
            "zone_health_reminder_hours": max(
                1,
                min(
                    24,
                    int(
                        tts.get(
                            "zone_health_reminder_hours",
                            default_tts.get("zone_health_reminder_hours", 1),
                        )
                        or 1
                    ),
                ),
            ),
            "zone_health_notification_msg": str(
                tts.get(
                    "zone_health_notification_msg",
                    default_tts.get(
                        "zone_health_notification_msg",
                        "Hi {name}, your Home Assistant Companion app location doesn't appear to be set up correctly. Zone-based presence isn't working.",
                    ),
                )
                or ""
            ),
            "zone_health_reminder_tts_msg": str(
                tts.get(
                    "zone_health_reminder_tts_msg",
                    default_tts.get(
                        "zone_health_reminder_tts_msg",
                        "{name}, your zone-based location setup needs attention. Please check your Companion app settings.",
                    ),
                )
                or ""
            ),
        }

        # Validate power enforcement settings
        pe = config.get("power_enforcement", {})
        default_pe = DEFAULT_CONFIG["energy"]["power_enforcement"]
        validated["power_enforcement"] = {
            "enabled": bool(pe.get("enabled", default_pe["enabled"])),
            "phase1_enabled": bool(pe.get("phase1_enabled", default_pe.get("phase1_enabled", True))),
            "phase2_enabled": bool(pe.get("phase2_enabled", default_pe.get("phase2_enabled", True))),
            "phase1_warning_count": max(1, int(pe.get("phase1_warning_count", default_pe["phase1_warning_count"]))),
            "phase1_time_window_minutes": max(1, int(pe.get("phase1_time_window_minutes", default_pe["phase1_time_window_minutes"]))),
            "phase1_volume_increment": max(1, min(20, int(pe.get("phase1_volume_increment", default_pe["phase1_volume_increment"])))),
            "phase1_reset_minutes": max(1, int(pe.get("phase1_reset_minutes", default_pe["phase1_reset_minutes"]))),
            "phase2_warning_count": max(1, int(pe.get("phase2_warning_count", default_pe["phase2_warning_count"]))),
            "phase2_time_window_minutes": max(1, int(pe.get("phase2_time_window_minutes", default_pe["phase2_time_window_minutes"]))),
            "phase2_reset_minutes": max(1, int(pe.get("phase2_reset_minutes", default_pe["phase2_reset_minutes"]))),
            "phase2_cycle_delay_seconds": max(1, min(30, int(pe.get("phase2_cycle_delay_seconds", default_pe["phase2_cycle_delay_seconds"])))),
            "phase2_max_volume": max(0, min(100, int(pe.get("phase2_max_volume", default_pe.get("phase2_max_volume", 100))))),
            "room_kwh_intervals": _normalize_room_kwh_intervals(
                pe.get("room_kwh_intervals", default_pe["room_kwh_intervals"])
            ),
            "home_kwh_limit": max(1, int(pe.get("home_kwh_limit", default_pe["home_kwh_limit"]))),
            "rooms_enabled": pe.get("rooms_enabled", default_pe["rooms_enabled"]),
        }

        # Validate statistics settings
        stats = config.get("statistics_settings", {})
        default_stats = DEFAULT_CONFIG["energy"]["statistics_settings"]
        default_refresh = int(default_stats.get("statistics_refresh_seconds", 60))
        validated["statistics_settings"] = {
            "billing_start_sensor": (stats.get("billing_start_sensor") or "").strip(),
            "billing_end_sensor": (stats.get("billing_end_sensor") or "").strip(),
            "current_usage_sensor": (stats.get("current_usage_sensor") or "").strip(),
            "projected_usage_sensor": (stats.get("projected_usage_sensor") or "").strip(),
            "kwh_cost_sensor": (stats.get("kwh_cost_sensor") or "").strip(),
            "statistics_refresh_seconds": max(
                15,
                min(600, _safe_int(stats.get("statistics_refresh_seconds"), default_refresh)),
            ),
        }

        default_eff = DEFAULT_CONFIG["energy"]["efficiency_settings"]
        es = config.get("efficiency_settings", {})
        if not isinstance(es, dict):
            es = {}
        validated["efficiency_settings"] = {
            "history_window_days": max(
                1,
                min(90, _safe_int(es.get("history_window_days"), default_eff["history_window_days"])),
            ),
            "engagement_lookback_days": max(
                1,
                min(
                    30,
                    _safe_int(es.get("engagement_lookback_days"), default_eff["engagement_lookback_days"]),
                ),
            ),
            "compliance_tolerance": max(
                1.0,
                min(1.5, _safe_float(es.get("compliance_tolerance"), default_eff["compliance_tolerance"])),
            ),
            "warning_points_per_event": max(
                0.25,
                min(
                    25.0,
                    _safe_float(es.get("warning_points_per_event"), default_eff["warning_points_per_event"]),
                ),
            ),
            "consumption_peer_multiplier": max(
                0.5,
                min(
                    5.0,
                    _safe_float(
                        es.get("consumption_peer_multiplier"),
                        default_eff["consumption_peer_multiplier"],
                    ),
                ),
            ),
            "load_high_watts": max(
                1.0,
                min(5000.0, _safe_float(es.get("load_high_watts"), default_eff["load_high_watts"])),
            ),
            "load_penalty_per_high_hour": max(
                0.0,
                min(
                    50.0,
                    _safe_float(
                        es.get("load_penalty_per_high_hour"),
                        default_eff["load_penalty_per_high_hour"],
                    ),
                ),
            ),
            "engagement_distinct_hours_target": max(
                1,
                min(
                    24,
                    _safe_int(
                        es.get("engagement_distinct_hours_target"),
                        default_eff["engagement_distinct_hours_target"],
                    ),
                ),
            ),
            "engagement_hours_weight": max(
                0.0,
                min(100.0, _safe_float(es.get("engagement_hours_weight"), default_eff["engagement_hours_weight"])),
            ),
            "engagement_visits_weight": max(
                0.0,
                min(
                    100.0,
                    _safe_float(es.get("engagement_visits_weight"), default_eff["engagement_visits_weight"]),
                ),
            ),
            "engagement_visits_daily_norm": max(
                1.0,
                min(
                    48.0,
                    _safe_float(
                        es.get("engagement_visits_daily_norm"),
                        default_eff["engagement_visits_daily_norm"],
                    ),
                ),
            ),
            "engagement_max_visits_per_hour": max(
                1,
                min(
                    10,
                    _safe_int(
                        es.get("engagement_max_visits_per_hour"),
                        default_eff["engagement_max_visits_per_hour"],
                    ),
                ),
            ),
            "efficiency_digest_enabled": _coerce_bool(
                es.get("efficiency_digest_enabled", default_eff["efficiency_digest_enabled"]),
                default_eff["efficiency_digest_enabled"],
            ),
            "efficiency_digest_time": _validate_budget_boost_announce_time(
                es.get("efficiency_digest_time"),
                str(default_eff["efficiency_digest_time"]),
            ),
            "efficiency_digest_title": str(
                es.get("efficiency_digest_title") or default_eff["efficiency_digest_title"]
            ),
            "efficiency_digest_message": str(
                es.get("efficiency_digest_message") or default_eff["efficiency_digest_message"]
            ),
        }

        return validated

    # Day energy tracking
    async def _async_load_energy_tracking(self) -> None:
        """Load day energy tracking data."""
        tracking_path = self._data_path("energy_tracking.json")
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

    async def async_save_persistent_data(self) -> None:
        """Save all persistent data (energy, intraday, enforcement, event counts). Call on unload/restart."""
        await self._async_save_energy_tracking()
        await self._async_save_intraday_history()
        await self._async_save_enforcement_state()
        await self._async_save_event_counts()

    async def _async_save_energy_tracking(self) -> None:
        """Save day energy tracking data."""
        tracking_path = self._data_path("energy_tracking.json")
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

    def record_intraday_power(self, entity_id: str, watts: float) -> None:
        """Record minute-by-minute power for 24-hour charts. Called from poll loop.
        Per-entity minute bucket: update in place for same minute, append when minute advances."""
        now = dt_util.now()
        minute_key = now.strftime("%Y-%m-%d %H:%M")
        if entity_id not in self._intraday_history:
            self._intraday_history[entity_id] = []
        hist = self._intraday_history[entity_id]
        if hist and hist[-1][0] == minute_key:
            hist[-1] = (minute_key, watts)
        else:
            hist.append((minute_key, watts))
        if len(hist) > 1440:
            self._intraday_history[entity_id] = hist[-1440:]

    def get_intraday_history(self, entity_id: str, minutes: int = 1440) -> list:
        """Get last N minutes of power history for an entity. Returns [(minute_key, watts), ...]"""
        history = self._intraday_history.get(entity_id, [])
        return history[-minutes:] if history else []

    def resolve_outlet_energy_tracking_key(
        self,
        room_id: str,
        outlet_index: int,
        plug_slot: int | None,
    ) -> str | None:
        """Tracking key for ``_intraday_history`` / day ledger for one outlet or one plug."""
        room = None
        for r in self.energy_config.get("rooms", []):
            rid = r.get("id", r["name"].lower().replace(" ", "_"))
            if rid == room_id:
                room = r
                break
        if not room:
            return None
        outlets = room.get("outlets") or []
        if outlet_index < 0 or outlet_index >= len(outlets):
            return None
        outlet = outlets[outlet_index]
        otype = outlet.get("type") or "outlet"

        if otype == "outlet":
            if plug_slot not in (1, 2):
                return None
            ent = (
                outlet.get("plug1_entity") if plug_slot == 1 else outlet.get("plug2_entity")
            )
            return str(ent).strip() if ent else None

        if otype == "light":
            if outlet.get("power_source") == "sensor":
                pe = outlet.get("power_sensor_entity")
                return str(pe).strip() if pe else None
            name = (outlet.get("name") or "light").lower().replace(" ", "_")
            return f"light_{room_id}_{name}"

        if otype in ("vent", "wall_heater"):
            if outlet.get("power_source") == "sensor":
                pe = outlet.get("power_sensor_entity")
                return str(pe).strip() if pe else None
            return vent_like_energy_tracking_key(room_id, outlet)

        if otype in ("single_outlet", "minisplit", "stove", "microwave", "fridge"):
            e = outlet.get("plug1_entity")
            return str(e).strip() if e else None

        return None

    def get_room_intraday_history(self, room_id: str, minutes: int = 1440) -> dict[str, Any]:
        """Get intraday power history for a room (sum of all outlets)."""
        room = None
        for r in self.energy_config.get("rooms", []):
            rid = r.get("id", r["name"].lower().replace(" ", "_"))
            if rid == room_id:
                room = r
                break
        if not room:
            return {"timestamps": [], "watts": []}
        
        # Collect all entity IDs / tracking keys for this room
        entity_ids = []
        for outlet in room.get("outlets", []):
            if outlet.get("type") == "light":
                if outlet.get("power_source") == "sensor":
                    pe = outlet.get("power_sensor_entity")
                    if pe:
                        entity_ids.append(pe)
                else:
                    key = f"light_{room_id}_{(outlet.get('name') or 'light').lower().replace(' ', '_')}"
                    entity_ids.append(key)
            elif outlet.get("type") in ("vent", "wall_heater"):
                if outlet.get("power_source") == "sensor":
                    pe = outlet.get("power_sensor_entity")
                    if pe:
                        entity_ids.append(pe)
                else:
                    key = vent_like_energy_tracking_key(room_id, outlet)
                    entity_ids.append(key)
            else:
                for e in (outlet.get("plug1_entity"), outlet.get("plug2_entity")):
                    if e:
                        entity_ids.append(e)
        
        # Merge histories - sum watts for each minute
        minute_sums: dict[str, float] = {}
        for eid in entity_ids:
            for minute_key, watts in self.get_intraday_history(eid, minutes):
                minute_sums[minute_key] = minute_sums.get(minute_key, 0) + watts
        
        # Sort by timestamp and return
        sorted_minutes = sorted(minute_sums.keys())
        return {
            "timestamps": sorted_minutes,
            "watts": [minute_sums[m] for m in sorted_minutes],
        }

    def get_total_intraday_history(self, minutes: int = 1440) -> dict[str, Any]:
        """Get intraday power history for all rooms combined."""
        minute_sums: dict[str, float] = {}
        for room in self.energy_config.get("rooms", []):
            rid = room.get("id", room["name"].lower().replace(" ", "_"))
            room_data = self.get_room_intraday_history(rid, minutes)
            for ts, w in zip(room_data["timestamps"], room_data["watts"]):
                minute_sums[ts] = minute_sums.get(ts, 0) + w
        sorted_minutes = sorted(minute_sums.keys())
        return {
            "timestamps": sorted_minutes,
            "watts": [minute_sums[m] for m in sorted_minutes],
        }

    def get_intraday_events(self, room_id: str | None = None) -> dict[str, Any]:
        """Get 24-hour intraday event counts (warnings/shutoffs) for charts.
        Returns hourly timestamps with cumulative values (0 to today's total over 24h)
        so charts match Current Power / Today's Usage format."""
        self._ensure_event_counts_for_today()
        today = dt_util.now().strftime("%Y-%m-%d")
        timestamps = [f"{today} {h:02d}:00" for h in range(24)]
        if room_id:
            warnings = self._event_counts.get("room_warnings", {}).get(room_id, 0)
            shutoffs = self._event_counts.get("room_shutoffs", {}).get(room_id, 0)
            power_cycles = self._event_counts.get("room_power_cycles", {}).get(room_id, 0)
            total_warnings = 0
            total_shutoffs = 0
            rooms_data = {}
        else:
            total_warnings = self._event_counts.get("total_warnings", 0)
            total_shutoffs = self._event_counts.get("total_shutoffs", 0)
            total_power_cycles = self._event_counts.get("total_power_cycles", 0)
            rooms_data = {}
            for rid in (r.get("id", r["name"].lower().replace(" ", "_")) for r in self.energy_config.get("rooms", [])):
                rooms_data[rid] = {
                    "warnings": self._event_counts.get("room_warnings", {}).get(rid, 0),
                    "shutoffs": self._event_counts.get("room_shutoffs", {}).get(rid, 0),
                    "power_cycles": self._event_counts.get("room_power_cycles", {}).get(rid, 0),
                }
        # Cumulative 0..total over 24 hours (linear distribution for chart continuity)
        def _cumul(n: int) -> list[float]:
            if n <= 0:
                return [0.0] * 24
            return [round((i + 1) * n / 24, 2) for i in range(24)]
        if room_id:
            return {
                "timestamps": timestamps,
                "warnings": _cumul(warnings),
                "shutoffs": _cumul(shutoffs),
                "power_cycles": _cumul(power_cycles),
            }
        return {
            "timestamps": timestamps,
            "total_warnings": _cumul(total_warnings),
            "total_shutoffs": _cumul(total_shutoffs),
            "total_power_cycles": _cumul(total_power_cycles),
            "rooms": {
                rid: {
                    "warnings": _cumul(r["warnings"]),
                    "shutoffs": _cumul(r["shutoffs"]),
                    "power_cycles": _cumul(r["power_cycles"]),
                }
                for rid, r in rooms_data.items()
            },
        }

    # Event count tracking (warnings and shutoffs) - per current date only
    def _ensure_event_counts_for_today(self) -> None:
        """Reset event counts if date has changed (new day)."""
        today = dt_util.now().strftime("%Y-%m-%d")
        if self._event_counts_reset_date != today:
            self._event_counts = {
                "total_warnings": 0,
                "total_shutoffs": 0,
                "total_power_cycles": 0,
                "room_warnings": {},
                "room_shutoffs": {},
                "room_power_cycles": {},
            }
            self._event_counts_reset_date = today

    async def _async_load_event_counts(self) -> None:
        """Load event counts (warnings and shutoffs). Reset if new day."""
        counts_path = self._data_path("event_counts.json")
        try:
            data = await self.hass.async_add_executor_job(
                _load_json_file, counts_path
            )
            if data is not None:
                self._event_counts_reset_date = data.get("last_reset_date")
                self._event_counts = {
                    "total_warnings": data.get("total_warnings", 0),
                    "total_shutoffs": data.get("total_shutoffs", 0),
                    "total_power_cycles": data.get("total_power_cycles", 0),
                    "room_warnings": data.get("room_warnings", {}),
                    "room_shutoffs": data.get("room_shutoffs", {}),
                    "room_power_cycles": data.get("room_power_cycles", {}),
                }
        except (json.JSONDecodeError, IOError):
            pass
        self._event_counts.setdefault("total_power_cycles", 0)
        self._event_counts.setdefault("room_power_cycles", {})
        self._ensure_event_counts_for_today()

    async def _async_save_event_counts(self) -> None:
        """Save event counts with current date."""
        counts_path = self._data_path("event_counts.json")
        payload = {
            "last_reset_date": self._event_counts_reset_date or dt_util.now().strftime("%Y-%m-%d"),
            "total_warnings": self._event_counts.get("total_warnings", 0),
            "total_shutoffs": self._event_counts.get("total_shutoffs", 0),
            "total_power_cycles": self._event_counts.get("total_power_cycles", 0),
            "room_warnings": self._event_counts.get("room_warnings", {}),
            "room_shutoffs": self._event_counts.get("room_shutoffs", {}),
            "room_power_cycles": self._event_counts.get("room_power_cycles", {}),
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

    async def async_increment_power_cycle(self, room_id: str) -> None:
        """Count one enforcement power-cycle run (phase 2, all outlets cycled together)."""
        self._ensure_event_counts_for_today()
        self._event_counts["total_power_cycles"] = self._event_counts.get("total_power_cycles", 0) + 1
        if room_id not in self._event_counts["room_power_cycles"]:
            self._event_counts["room_power_cycles"][room_id] = 0
        self._event_counts["room_power_cycles"][room_id] += 1
        await self._async_save_event_counts()

    async def async_record_power_cycle_initiated(
        self,
        room_id: str,
        room_name: str,
        *,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """One count when phase-2 outlet power cycle is initiated (not per plug)."""
        await self.async_increment_power_cycle(room_id)
        await self.async_add_event_log_entry(
            room_id, room_name, "power_cycle", None, True, extra=extra
        )

    def get_event_counts(self) -> dict[str, Any]:
        """Get event counts for current date only."""
        self._ensure_event_counts_for_today()
        return self._event_counts.copy()

    # Event log (24h warnings/shutoffs with TTS success/fail)
    EVENT_LOG_FILE = "event_log.json"
    EVENT_ARCHIVE_FILE = "event_archive.json"
    EVENT_ARCHIVE_RETENTION_DAYS = 120
    EVENT_ARCHIVE_MAX_PER_DAY = 2000
    EVENT_LOG_API_MAX_ENTRIES = 5000

    async def _async_load_event_log(self) -> None:
        """Load event log from file."""
        path = self._data_path(self.EVENT_LOG_FILE)
        try:
            data = await self.hass.async_add_executor_job(_load_json_file, path)
            self._event_log = data.get("events", []) if data else []
        except (json.JSONDecodeError, IOError):
            self._event_log = []

    async def _async_save_event_log(self) -> None:
        """Save event log to file (keep last N entries)."""
        path = self._data_path(self.EVENT_LOG_FILE)
        payload = {"events": self._event_log[-self._event_log_max_entries :]}
        try:
            await self.hass.async_add_executor_job(_write_json_file, path, payload)
        except IOError as err:
            _LOGGER.error("Error saving event log: %s", err)

    def _merge_event_log_into_archive(self) -> None:
        """Backfill rolling _event_log into per-day archive (deduped)."""
        for e in self._event_log:
            ts = e.get("ts") or ""
            if len(ts) < 10:
                continue
            day = ts[:10]
            bucket = self._event_archive_days.setdefault(day, [])
            k = _event_log_dedupe_key(e)
            if any(_event_log_dedupe_key(x) == k for x in bucket):
                continue
            bucket.append(dict(e))
        for d, bucket in list(self._event_archive_days.items()):
            bucket.sort(key=lambda x: str(x.get("ts") or ""))
            if len(bucket) > self.EVENT_ARCHIVE_MAX_PER_DAY:
                self._event_archive_days[d] = bucket[-self.EVENT_ARCHIVE_MAX_PER_DAY :]

    async def _async_load_event_archive(self) -> None:
        """Load per-day event archive; merge rolling log for same-day recovery."""
        path = self._data_path(self.EVENT_ARCHIVE_FILE)
        try:
            data = await self.hass.async_add_executor_job(_load_json_file, path)
            raw = (data or {}).get("days") or {}
            self._event_archive_days = {
                str(k): list(v) if isinstance(v, list) else []
                for k, v in raw.items()
                if isinstance(k, str) and len(str(k)) == 10
            }
        except (json.JSONDecodeError, IOError, TypeError):
            self._event_archive_days = {}
        self._merge_event_log_into_archive()

    def _prune_event_archive_days(self) -> None:
        """Drop archive days older than retention window."""
        now = dt_util.now().date()
        cutoff = now - timedelta(days=self.EVENT_ARCHIVE_RETENTION_DAYS)
        cutoff_str = cutoff.strftime("%Y-%m-%d")
        for d in list(self._event_archive_days.keys()):
            if d < cutoff_str:
                del self._event_archive_days[d]

    async def _async_save_event_archive(self) -> None:
        """Persist event archive after pruning old days."""
        self._prune_event_archive_days()
        path = self._data_path(self.EVENT_ARCHIVE_FILE)
        try:
            await self.hass.async_add_executor_job(
                _write_json_file, path, {"days": self._event_archive_days}
            )
        except IOError as err:
            _LOGGER.error("Error saving event archive: %s", err)

    @staticmethod
    def _iter_archive_dates_inclusive(start: str, end: str) -> list[str]:
        """List YYYY-MM-DD from start through end inclusive."""
        try:
            d0 = datetime.strptime(start[:10], "%Y-%m-%d").date()
            d1 = datetime.strptime(end[:10], "%Y-%m-%d").date()
        except ValueError:
            return []
        out: list[str] = []
        cur = d0
        while cur <= d1:
            out.append(cur.strftime("%Y-%m-%d"))
            cur += timedelta(days=1)
        return out

    async def async_add_event_log_entry(
        self,
        room_id: str,
        room_name: str,
        event_type: str,  # "warning", "shutoff", or "power_cycle"
        outlet_name: str | None,
        tts_succeeded: bool,
        *,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Add an event to the log (threshold warning or shutoff with TTS result)."""
        now = dt_util.now()
        entry = {
            "ts": now.strftime("%Y-%m-%dT%H:%M:%S"),
            "room_id": room_id,
            "room_name": room_name,
            "type": event_type,
            "outlet_name": outlet_name,
            "tts_succeeded": tts_succeeded,
        }
        if extra:
            entry.update({k: v for k, v in extra.items() if v is not None})
        self._event_log.append(entry)
        if len(self._event_log) > self._event_log_max_entries:
            self._event_log = self._event_log[-self._event_log_max_entries :]
        await self._async_save_event_log()

        day_key = (entry.get("ts") or "")[:10]
        if len(day_key) == 10:
            bucket = self._event_archive_days.setdefault(day_key, [])
            k = _event_log_dedupe_key(entry)
            if not any(_event_log_dedupe_key(x) == k for x in bucket):
                bucket.append(entry)
            bucket.sort(key=lambda x: str(x.get("ts") or ""))
            if len(bucket) > self.EVENT_ARCHIVE_MAX_PER_DAY:
                self._event_archive_days[day_key] = bucket[
                    -self.EVENT_ARCHIVE_MAX_PER_DAY :
                ]
        await self._async_save_event_archive()

    def get_event_log(
        self,
        room_id: str | None = None,
        since_hours: int | None = 24,
        date_start: str | None = None,
        date_end: str | None = None,
    ) -> tuple[list[dict[str, Any]], bool]:
        """Return (events newest first, truncated).

        If date_start and date_end (YYYY-MM-DD) are set, return all archived events
        in that inclusive range (plus deduped merge). Otherwise use a sliding window
        of since_hours (clamped), merging archive days that overlap the window with
        the rolling _event_log.
        """
        max_n = self.EVENT_LOG_API_MAX_ENTRIES
        truncated = False

        if date_start and date_end:
            ds = str(date_start).strip()[:10]
            de = str(date_end).strip()[:10]
            if len(ds) != 10 or len(de) != 10 or ds > de:
                return [], False
            days = self._iter_archive_dates_inclusive(ds, de)
            seen: set[tuple[Any, ...]] = set()
            collected: list[dict[str, Any]] = []
            for day in days:
                for e in self._event_archive_days.get(day, []):
                    if room_id and e.get("room_id") != room_id:
                        continue
                    k = _event_log_dedupe_key(e)
                    if k in seen:
                        continue
                    seen.add(k)
                    collected.append(e)
            collected.sort(key=lambda x: str(x.get("ts") or ""), reverse=True)
            if len(collected) > max_n:
                return collected[:max_n], True
            return collected, False

        sh = 24 if since_hours is None else int(since_hours)
        sh = max(1, min(24 * 90, sh))
        cutoff = dt_util.now() - timedelta(hours=sh)
        cutoff_ts = cutoff.strftime("%Y-%m-%dT%H:%M:%S")
        cutoff_day = cutoff.strftime("%Y-%m-%d")
        today = dt_util.now().strftime("%Y-%m-%d")
        days = self._iter_archive_dates_inclusive(cutoff_day, today)
        seen: set[tuple[Any, ...]] = set()
        collected: list[dict[str, Any]] = []
        for day in days:
            for e in self._event_archive_days.get(day, []):
                if e.get("ts", "") < cutoff_ts:
                    continue
                if room_id and e.get("room_id") != room_id:
                    continue
                k = _event_log_dedupe_key(e)
                if k in seen:
                    continue
                seen.add(k)
                collected.append(e)
        for e in reversed(self._event_log):
            if e.get("ts", "") < cutoff_ts:
                break
            if room_id and e.get("room_id") != room_id:
                continue
            k = _event_log_dedupe_key(e)
            if k in seen:
                continue
            seen.add(k)
            collected.append(e)
        collected.sort(key=lambda x: str(x.get("ts") or ""), reverse=True)
        if len(collected) > max_n:
            return collected[:max_n], True
        return collected, False

    # Daily totals history (end-of-day snapshots for 30-day graphs)
    async def _async_load_daily_totals(self) -> None:
        """Load daily totals history from file."""
        path = self._data_path("daily_totals.json")
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
        path = self._data_path("daily_totals.json")
        try:
            await self.hass.async_add_executor_job(
                _write_json_file, path, {"days": self._daily_totals}
            )
        except IOError as err:
            _LOGGER.error("Error saving daily totals: %s", err)

    async def _async_load_statistics_cache(self) -> None:
        """Load pre-computed statistics cache from file for instant page load."""
        path = self._data_path("statistics_cache.json")
        try:
            data = await self.hass.async_add_executor_job(_load_json_file, path)
            self._statistics_cache_data = data if data else {}
        except (json.JSONDecodeError, IOError):
            self._statistics_cache_data = {}

    async def async_save_statistics_cache(self, data: dict[str, Any]) -> None:
        """Save pre-computed statistics to file for instant page load."""
        self._statistics_cache_data = data
        path = self._data_path("statistics_cache.json")
        try:
            await self.hass.async_add_executor_job(_write_json_file, path, data)
        except IOError as err:
            _LOGGER.error("Error saving statistics cache: %s", err)

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
                    if outlet.get("power_source") == "sensor":
                        pe = outlet.get("power_sensor_entity")
                        if pe:
                            room_wh += self._day_energy_data.get(pe, {}).get("energy", 0.0)
                    else:
                        key = f"light_{room_id}_{(outlet.get('name') or 'light').lower().replace(' ', '_')}"
                        room_wh += self._day_energy_data.get(key, {}).get("energy", 0.0)
                elif outlet.get("type") in ("vent", "wall_heater"):
                    if outlet.get("power_source") == "sensor":
                        pe = outlet.get("power_sensor_entity")
                        if pe:
                            room_wh += self._day_energy_data.get(pe, {}).get("energy", 0.0)
                    else:
                        key = vent_like_energy_tracking_key(room_id, outlet)
                        room_wh += self._day_energy_data.get(key, {}).get("energy", 0.0)
                else:
                    for e in (outlet.get("plug1_entity"), outlet.get("plug2_entity")):
                        if e:
                            room_wh += self._day_energy_data.get(e, {}).get("energy", 0.0)

            rooms_data[room_id] = {
                "wh": round(room_wh, 2),
                "warnings": self._event_counts.get("room_warnings", {}).get(room_id, 0),
                "shutoffs": self._event_counts.get("room_shutoffs", {}).get(room_id, 0),
                "power_cycles": self._event_counts.get("room_power_cycles", {}).get(room_id, 0),
            }

        total_wh = sum(r["wh"] for r in rooms_data.values())
        self._daily_totals[old_date] = {
            "total_wh": round(total_wh, 2),
            "total_warnings": self._event_counts.get("total_warnings", 0),
            "total_shutoffs": self._event_counts.get("total_shutoffs", 0),
            "total_power_cycles": self._event_counts.get("total_power_cycles", 0),
            "rooms": rooms_data,
        }
        await self._async_save_daily_totals()

        self._day_energy_data = {}
        self._last_reset_date = today
        self._last_power_update = {}
        self._event_counts = {
            "total_warnings": 0,
            "total_shutoffs": 0,
            "total_power_cycles": 0,
            "room_warnings": {},
            "room_shutoffs": {},
            "room_power_cycles": {},
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
                    if outlet.get("power_source") == "sensor":
                        pe = outlet.get("power_sensor_entity")
                        if pe:
                            room_wh += self._day_energy_data.get(pe, {}).get("energy", 0.0)
                    else:
                        key = f"light_{rid}_{(outlet.get('name') or 'light').lower().replace(' ', '_')}"
                        room_wh += self._day_energy_data.get(key, {}).get("energy", 0.0)
                elif outlet.get("type") in ("vent", "wall_heater"):
                    if outlet.get("power_source") == "sensor":
                        pe = outlet.get("power_sensor_entity")
                        if pe:
                            room_wh += self._day_energy_data.get(pe, {}).get("energy", 0.0)
                    else:
                        key = vent_like_energy_tracking_key(rid, outlet)
                        room_wh += self._day_energy_data.get(key, {}).get("energy", 0.0)
                else:
                    for e in (outlet.get("plug1_entity"), outlet.get("plug2_entity")):
                        if e:
                            room_wh += self._day_energy_data.get(e, {}).get("energy", 0.0)
            rooms_data[rid] = {
                "wh": round(room_wh, 2),
                "warnings": self._event_counts.get("room_warnings", {}).get(rid, 0),
                "shutoffs": self._event_counts.get("room_shutoffs", {}).get(rid, 0),
                "power_cycles": self._event_counts.get("room_power_cycles", {}).get(rid, 0),
            }
        total_wh = sum(r["wh"] for r in rooms_data.values())
        return {
            "total_wh": round(total_wh, 2),
            "total_warnings": self._event_counts.get("total_warnings", 0),
            "total_shutoffs": self._event_counts.get("total_shutoffs", 0),
            "total_power_cycles": self._event_counts.get("total_power_cycles", 0),
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
        result = {
            "dates": [],
            "total_wh": [],
            "total_warnings": [],
            "total_shutoffs": [],
            "total_power_cycles": [],
            "rooms": {},
        }
        for rid in all_room_ids:
            result["rooms"][rid] = {"wh": [], "warnings": [], "shutoffs": [], "power_cycles": []}

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
            result["total_power_cycles"].append(row.get("total_power_cycles", 0))
            row_rooms = row.get("rooms") or {}
            for rid in all_room_ids:
                rdata = row_rooms.get(rid, {})
                result["rooms"][rid]["wh"].append(rdata.get("wh", 0))
                result["rooms"][rid]["warnings"].append(rdata.get("warnings", 0))
                result["rooms"][rid]["shutoffs"].append(rdata.get("shutoffs", 0))
                result["rooms"][rid]["power_cycles"].append(rdata.get("power_cycles", 0))

        return result

    def get_daily_history_for_range(self, date_start: str, date_end: str) -> dict[str, Any]:
        """Daily totals for each calendar day in [date_start, date_end] inclusive (YYYY-MM-DD).
        Missing past days use zeros so charts span the full billing window."""
        from datetime import datetime, timedelta

        today = dt_util.now().strftime("%Y-%m-%d")
        all_room_ids = {
            r.get("id", r["name"].lower().replace(" ", "_"))
            for r in self.energy_config.get("rooms", [])
        }
        result: dict[str, Any] = {
            "dates": [],
            "total_wh": [],
            "total_warnings": [],
            "total_shutoffs": [],
            "total_power_cycles": [],
            "rooms": {
                rid: {"wh": [], "warnings": [], "shutoffs": [], "power_cycles": []}
                for rid in all_room_ids
            },
        }
        try:
            cur = datetime.strptime(date_start, "%Y-%m-%d")
            end_dt = datetime.strptime(date_end, "%Y-%m-%d")
        except ValueError:
            return result
        if end_dt < cur:
            return result

        while cur <= end_dt:
            d = cur.strftime("%Y-%m-%d")
            if d > today:
                break
            if d == today:
                row = self._build_today_totals()
            else:
                row = self._daily_totals.get(d)
                if row is None:
                    row = {
                        "total_wh": 0,
                        "total_warnings": 0,
                        "total_shutoffs": 0,
                        "total_power_cycles": 0,
                        "rooms": {},
                    }
            result["dates"].append(d)
            result["total_wh"].append(row.get("total_wh", 0))
            result["total_warnings"].append(row.get("total_warnings", 0))
            result["total_shutoffs"].append(row.get("total_shutoffs", 0))
            result["total_power_cycles"].append(row.get("total_power_cycles", 0))
            row_rooms = row.get("rooms") or {}
            for rid in all_room_ids:
                rdata = row_rooms.get(rid) or {}
                result["rooms"][rid]["wh"].append(rdata.get("wh", 0))
                result["rooms"][rid]["warnings"].append(rdata.get("warnings", 0))
                result["rooms"][rid]["shutoffs"].append(rdata.get("shutoffs", 0))
                result["rooms"][rid]["power_cycles"].append(rdata.get("power_cycles", 0))
            cur += timedelta(days=1)

        return result

    # Billing history (for new-cycle alerts)
    async def _async_load_billing_history(self) -> None:
        """Load billing history from file."""
        path = self._data_path("billing_history.json")
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
        path = self._data_path("billing_history.json")
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

    def _is_valid_date(self, date_str: str | None) -> bool:
        """Check if string is a valid YYYY-MM-DD date."""
        if not date_str:
            return False
        return bool(re.match(r"^\d{4}-\d{2}-\d{2}$", date_str))

    def get_statistics_date_range(
        self, date_start: str | None = None, date_end: str | None = None
    ) -> tuple[str, str, bool]:
        """Resolve final date range. Returns (start, end, is_narrowed).
        Uses billing cycle dates; includes today if billing end is in the past.
        Optional date_start/date_end (YYYY-MM-DD) narrow the range, clamped to billing/base."""
        today = dt_util.now().strftime("%Y-%m-%d")
        billing_start, billing_end = self.get_billing_date_range()

        if billing_start and billing_end:
            base_start = billing_start
            base_end = billing_end
        else:
            # Fall back to last 31 days when no billing sensors are configured
            base_start = (dt_util.now() - timedelta(days=30)).strftime("%Y-%m-%d")
            base_end = today

        # Include today if within range
        if base_start <= today <= base_end:
            pass  # today is in range
        elif today > base_end:
            base_end = today  # extend to today if billing end is in the past

        # Never return invalid or inverted ranges (empty stats / missing graphs)
        if (
            not self._is_valid_date(base_start)
            or not self._is_valid_date(base_end)
            or base_start > base_end
        ):
            base_start = (dt_util.now() - timedelta(days=30)).strftime("%Y-%m-%d")
            base_end = today

        ds = (date_start or "").strip() or None
        de = (date_end or "").strip() or None
        if (
            ds
            and de
            and self._is_valid_date(ds)
            and self._is_valid_date(de)
            and ds <= de
        ):
            u_start = max(ds, base_start)
            u_end = min(de, base_end)
            if u_start <= u_end:
                return (u_start, u_end, True)

        return (base_start, base_end, False)

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

    # Power enforcement
    def _ensure_enforcement_state_for_today(self) -> None:
        """Reset enforcement state if date changed (new day)."""
        today = dt_util.now().strftime("%Y-%m-%d")
        if self._enforcement_reset_date != today:
            self._enforcement_state = {}
            self._home_kwh_alert_sent = False
            self._enforcement_reset_date = today

    def get_enforcement_state(self, room_id: str) -> dict:
        """Get enforcement state for a room."""
        self._ensure_enforcement_state_for_today()
        if room_id not in self._enforcement_state:
            self._enforcement_state[room_id] = {
                "warnings": [],  # [(timestamp, watts), ...]
                "phase": 0,  # 0=normal, 1=volume escalation, 2=power cycling
                "volume_offset": 0,  # Current volume increase (0-100)
                "last_phase_change": None,
                "kwh_alerts_sent": [],  # [5, 10, 15, ...]
            }
        return self._enforcement_state[room_id]

    async def async_record_threshold_warning(self, room_id: str, watts: float) -> None:
        """Record a threshold warning with timestamp."""
        self._ensure_enforcement_state_for_today()
        state = self.get_enforcement_state(room_id)
        now = dt_util.now()
        state["warnings"].append((now.isoformat(), watts))
        # Keep only warnings from the last hour
        cutoff = (now - timedelta(hours=1)).isoformat()
        state["warnings"] = [(ts, w) for ts, w in state["warnings"] if ts >= cutoff]
        await self._async_save_enforcement_state()

    def get_warnings_in_window(self, room_id: str, minutes: int) -> int:
        """Count warnings in the last N minutes."""
        state = self.get_enforcement_state(room_id)
        now = dt_util.now()
        cutoff = (now - timedelta(minutes=minutes)).isoformat()
        return sum(1 for ts, _ in state["warnings"] if ts >= cutoff)

    def check_phase_reset(self, room_id: str, reset_minutes: int) -> bool:
        """Check if room has been below threshold long enough to reset phase."""
        state = self.get_enforcement_state(room_id)
        if not state["warnings"]:
            return True
        last_warning_ts = max(ts for ts, _ in state["warnings"])
        try:
            last_warning = datetime.fromisoformat(last_warning_ts)
            return (dt_util.now() - last_warning).total_seconds() >= (reset_minutes * 60)
        except (ValueError, TypeError):
            return False

    async def async_set_enforcement_phase(self, room_id: str, phase: int) -> None:
        """Set the enforcement phase for a room."""
        state = self.get_enforcement_state(room_id)
        if state["phase"] != phase:
            state["phase"] = phase
            state["last_phase_change"] = dt_util.now().isoformat()
            if phase == 0:
                state["volume_offset"] = 0  # Reset volume on phase reset
            await self._async_save_enforcement_state()

    async def async_increment_volume_offset(self, room_id: str, increment: int, max_offset: int = 100) -> int:
        """Increase volume offset for a room. Returns new offset."""
        state = self.get_enforcement_state(room_id)
        current = int(state.get("volume_offset", 0) or 0)
        state["volume_offset"] = min(max_offset, current + increment)
        await self._async_save_enforcement_state()
        return state["volume_offset"]

    def get_room_day_kwh(self, room_id: str) -> float:
        """Get total kWh for a room today."""
        room_wh = 0.0
        for room in self.energy_config.get("rooms", []):
            rid = room.get("id", room["name"].lower().replace(" ", "_"))
            if rid != room_id:
                continue
            for outlet in room.get("outlets", []):
                if outlet.get("type") == "light":
                    if outlet.get("power_source") == "sensor":
                        pe = outlet.get("power_sensor_entity")
                        if pe:
                            room_wh += self._day_energy_data.get(pe, {}).get("energy", 0.0)
                    else:
                        key = f"light_{rid}_{(outlet.get('name') or 'light').lower().replace(' ', '_')}"
                        room_wh += self._day_energy_data.get(key, {}).get("energy", 0.0)
                elif outlet.get("type") in ("vent", "wall_heater"):
                    if outlet.get("power_source") == "sensor":
                        pe = outlet.get("power_sensor_entity")
                        if pe:
                            room_wh += self._day_energy_data.get(pe, {}).get("energy", 0.0)
                    else:
                        key = vent_like_energy_tracking_key(rid, outlet)
                        room_wh += self._day_energy_data.get(key, {}).get("energy", 0.0)
                else:
                    for e in (outlet.get("plug1_entity"), outlet.get("plug2_entity")):
                        if e:
                            room_wh += self._day_energy_data.get(e, {}).get("energy", 0.0)
        return room_wh / 1000.0

    def get_total_day_kwh(self) -> float:
        """Get total kWh for all rooms today."""
        total_kwh = 0.0
        for room in self.energy_config.get("rooms", []):
            rid = room.get("id", room["name"].lower().replace(" ", "_"))
            total_kwh += self.get_room_day_kwh(rid)
        return total_kwh

    def get_room_percentage_of_total(self, room_id: str) -> float:
        """Get percentage of total home usage for a room."""
        total_kwh = self.get_total_day_kwh()
        if total_kwh <= 0:
            return 0.0
        room_kwh = self.get_room_day_kwh(room_id)
        return round((room_kwh / total_kwh) * 100, 1)

    async def async_should_send_room_kwh_alert(
        self, room_id: str, intervals: list
    ) -> float | None:
        """Check if a kWh interval alert should be sent. Returns threshold or None."""
        state = self.get_enforcement_state(room_id)
        room_kwh = self.get_room_day_kwh(room_id)
        sent = state["kwh_alerts_sent"]
        sent_keys = {_room_kwh_alert_threshold_key(s) for s in sent}
        for interval in sorted(float(x) for x in intervals):
            ik = _room_kwh_alert_threshold_key(interval)
            if room_kwh >= interval - 1e-9 and ik not in sent_keys:
                sent.append(ik)
                sent_keys.add(ik)
                await self._async_save_enforcement_state()
                return ik
        return None

    async def async_should_send_home_kwh_alert(self, limit: int) -> bool:
        """Check if home kWh alert should be sent."""
        self._ensure_enforcement_state_for_today()
        if self._home_kwh_alert_sent:
            return False
        if self.get_total_day_kwh() >= limit:
            self._home_kwh_alert_sent = True
            await self._async_save_enforcement_state()
            return True
        return False

    # Enforcement state persistence
    async def _async_load_enforcement_state(self) -> None:
        """Load enforcement state from file."""
        path = self._data_path("enforcement_state.json")
        try:
            data = await self.hass.async_add_executor_job(_load_json_file, path)
            if data is not None:
                self._enforcement_reset_date = data.get("reset_date")
                self._enforcement_state = data.get("rooms", {})
                self._home_kwh_alert_sent = data.get("home_kwh_alert_sent", False)
        except (json.JSONDecodeError, IOError):
            pass
        # Reset if new day
        self._ensure_enforcement_state_for_today()

    async def _async_save_enforcement_state(self) -> None:
        """Save enforcement state to file."""
        path = self._data_path("enforcement_state.json")
        payload = {
            "reset_date": self._enforcement_reset_date,
            "rooms": self._enforcement_state,
            "home_kwh_alert_sent": self._home_kwh_alert_sent,
        }
        try:
            await self.hass.async_add_executor_job(_write_json_file, path, payload)
        except IOError as err:
            _LOGGER.error("Error saving enforcement state: %s", err)

    # Intraday history persistence
    async def _async_load_intraday_history(self) -> None:
        """Load intraday power history from file."""
        path = self._data_path("intraday_history.json")
        try:
            data = await self.hass.async_add_executor_job(_load_json_file, path)
            if data is not None:
                saved_date = data.get("date")
                today = dt_util.now().strftime("%Y-%m-%d")
                # Only load if data is from today
                if saved_date == today:
                    self._intraday_history = data.get("history", {})
                    self._intraday_last_minute = data.get("last_minute", "")
                else:
                    # Data is from a previous day, start fresh
                    self._intraday_history = {}
                    self._intraday_last_minute = ""
        except (json.JSONDecodeError, IOError):
            pass

    async def _async_save_intraday_history(self) -> None:
        """Save intraday power history to file."""
        path = self._data_path("intraday_history.json")
        today = dt_util.now().strftime("%Y-%m-%d")
        payload = {
            "date": today,
            "history": self._intraday_history,
        }
        try:
            await self.hass.async_add_executor_job(_write_json_file, path, payload)
        except IOError as err:
            _LOGGER.error("Error saving intraday history: %s", err)
