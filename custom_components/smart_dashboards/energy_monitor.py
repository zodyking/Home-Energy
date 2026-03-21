"""Energy monitoring background task for Smart Dashboards."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    ALERT_COOLDOWN,
    DEFAULT_BUDGET_EXCEEDED_MSG,
    DEFAULT_BUDGET_BOOST_SCHEDULED_MSG,
    ENERGY_CHECK_INTERVAL,
    SHUTOFF_RESET_DELAY,
    STOVE_WARNING_TIMER,
    STOVE_SHUTOFF_TIMER,
    DEFAULT_TTS_PREFIX,
    DEFAULT_ROOM_WARN_MSG,
    DEFAULT_OUTLET_WARN_MSG,
    DEFAULT_SHUTOFF_MSG,
    DEFAULT_BREAKER_WARN_MSG,
    DEFAULT_BREAKER_SHUTOFF_MSG,
    DEFAULT_STOVE_ON_MSG,
    DEFAULT_STOVE_OFF_MSG,
    DEFAULT_STOVE_TIMER_STARTED_MSG,
    DEFAULT_STOVE_15MIN_WARN_MSG,
    DEFAULT_STOVE_30SEC_WARN_MSG,
    DEFAULT_STOVE_TIMER_PROGRESS_MSG,
    DEFAULT_STOVE_AUTO_OFF_MSG,
    DEFAULT_MICROWAVE_CUT_MSG,
    DEFAULT_MICROWAVE_RESTORE_MSG,
    DEFAULT_MINISPLIT_PHASE2_WARN_MSG,
    DEFAULT_MINISPLIT_PHASE2_AFTER_MSG,
    DEFAULT_MINISPLIT_PHASE2_RESTORE_MSG,
)
from .tts_helper import async_send_tts
from .tts_queue import async_send_tts_or_queue
from .tts_numbers import spoken_cardinal

if TYPE_CHECKING:
    from .config_manager import ConfigManager

_LOGGER = logging.getLogger(__name__)


class EnergyMonitor:
    """Monitor energy consumption and send TTS alerts for thresholds."""

    def __init__(self, hass: HomeAssistant, config_manager: "ConfigManager") -> None:
        """Initialize the energy monitor."""
        self.hass = hass
        self.config_manager = config_manager
        self._running = False
        self._task: asyncio.Task | None = None
        self._last_room_alerts: dict[str, datetime] = {}
        self._last_outlet_alerts: dict[str, datetime] = {}
        self._last_plug_alerts: dict[str, datetime] = {}
        self._last_breaker_warnings: dict[str, datetime] = {}
        self._last_breaker_shutoffs: dict[str, datetime] = {}
        self._breaker_shutoff_pending: dict[str, bool] = {}  # Track breakers in shutoff cycle
        self._shutoff_pending: dict[str, bool] = {}  # Track plugs in shutoff cycle
        self._save_counter = 0
        
        # Stove safety state (keyed by stove_plug_entity for multi-stove support)
        self._stove_state: dict[str, str] = {}
        self._stove_timer_start: dict[str, datetime | None] = {}
        self._stove_timer_phase: dict[str, str] = {}
        self._stove_last_presence: dict[str, str | None] = {}
        self._stove_15min_warn_sent: dict[str, bool] = {}
        self._stove_30sec_warn_sent: dict[str, bool] = {}
        self._stove_powered_off_by_microwave: dict[str, bool] = {}
        self._stove_power_below_since: dict[str, datetime | None] = {}
        self._stove_power_above_since: dict[str, datetime | None] = {}
        self._stove_presence_window_start: dict[str, datetime | None] = {}
        self._power_listener_unsub: list = []  # Unsubscribe callbacks for state listeners
        self._room_budget_announced: set[str] = set()
        self._room_budget_announced_date: str = ""
        self._budget_boost_scheduled_fired_date: str = ""
        self._budget_boost_slots_fired: dict[str, list[int]] = {}
        self._stove_progress_last_boundary: dict[str, int] = {}
        # Phase-2 mini-split hold: room_id -> {switches: set[str], outlet_name, volume}
        self._minisplit_hold: dict[str, dict] = {}

    @staticmethod
    def _budget_boost_period_label(weekdays: list) -> str:
        """Phrase for TTS: weekend only when Sat+Sun; else 'on Monday and Tuesday' style."""
        names = [
            "Monday",
            "Tuesday",
            "Wednesday",
            "Thursday",
            "Friday",
            "Saturday",
            "Sunday",
        ]
        try:
            wk = sorted({int(d) for d in weekdays if 0 <= int(d) <= 6})
        except (TypeError, ValueError):
            wk = []
        if not wk:
            return "on selected days"
        if set(wk) == {5, 6}:
            return "for the weekend"
        if len(wk) == 1:
            return f"on {names[wk[0]]}"
        if len(wk) == 2:
            return f"on {names[wk[0]]} and {names[wk[1]]}"
        return "on " + ", ".join(names[d] for d in wk[:-1]) + f", and {names[wk[-1]]}"

    def _is_budget_boost_day(self, now: datetime, tts_settings: dict) -> bool:
        if not tts_settings.get("budget_boost_enabled"):
            return False
        mult = float(tts_settings.get("budget_boost_multiplier") or 1)
        if mult <= 1:
            return False
        days = tts_settings.get("budget_boost_weekdays") or []
        if not days:
            return False
        return now.weekday() in days

    def _effective_kwh_budget(self, base: float, now: datetime, tts_settings: dict) -> float:
        return self.config_manager.effective_kwh_budget_for_moment(base, now, tts_settings)

    @staticmethod
    def _budget_multiplier_tts_str(mult: float) -> str:
        if mult == int(mult):
            return str(int(mult))
        return str(mult).rstrip("0").rstrip(".")

    def _budget_boost_slots_path(self) -> str:
        return self.hass.config.path("smart_dashboards_budget_boost_slots.json")

    async def _async_load_budget_boost_slots(self) -> None:
        path = self._budget_boost_slots_path()
        try:
            def _read() -> dict | None:
                if not os.path.isfile(path):
                    return None
                with open(path, encoding="utf-8") as f:
                    return json.load(f)

            data = await self.hass.async_add_executor_job(_read)
            if isinstance(data, dict):
                self._budget_boost_slots_fired = {
                    str(k): [int(x) for x in v]
                    for k, v in data.items()
                    if isinstance(v, list)
                }
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as err:
            _LOGGER.debug("Budget boost slots load skipped: %s", err)

    async def _async_save_budget_boost_slots(self) -> None:
        path = self._budget_boost_slots_path()

        def _write() -> None:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._budget_boost_slots_fired, f, indent=2)

        try:
            await self.hass.async_add_executor_job(_write)
        except OSError as err:
            _LOGGER.warning("Budget boost slots save failed: %s", err)

    @staticmethod
    def _parse_hhmm_to_minutes(s: str | None, default_h: int, default_m: int) -> int:
        if not s:
            return default_h * 60 + default_m
        try:
            parts = str(s).strip().replace(".", ":").split(":")
            h = int(parts[0])
            mi = int(parts[1]) if len(parts) > 1 else 0
            if 0 <= h <= 23 and 0 <= mi <= 59:
                return h * 60 + mi
        except (ValueError, IndexError, TypeError):
            pass
        return default_h * 60 + default_m

    @staticmethod
    def _iter_budget_boost_slot_minutes(
        t0: int, t1: int, repeat_min: int, minute_offset: int
    ) -> list[int]:
        """Slot start times as minutes from midnight, inclusive window [t0, t1]."""
        if t1 < t0:
            t0, t1 = t1, t0
        repeat_min = max(15, repeat_min)
        mo = max(0, min(59, minute_offset))
        slots: list[int] = []
        t = t0
        while t % 60 != mo and t <= t1:
            t += 1
        while t <= t1:
            slots.append(t)
            t += repeat_min
        return slots

    async def _maybe_fire_budget_boost_scheduled(
        self, now: datetime, today: str, tts_settings: dict
    ) -> None:
        """On boost days, TTS at each repeat slot inside the configured time window."""
        if not self._is_budget_boost_day(now, tts_settings):
            return
        mp = (
            str(tts_settings.get("tts_default_media_player") or "").strip()
            or str(tts_settings.get("budget_boost_announce_media_player") or "").strip()
        )
        if not mp:
            return
        start_s = str(tts_settings.get("budget_boost_window_start") or "").strip() or str(
            tts_settings.get("budget_boost_announce_time") or "09:00"
        )
        end_s = str(tts_settings.get("budget_boost_window_end") or "").strip() or "21:00"
        t0 = self._parse_hhmm_to_minutes(start_s, 9, 0)
        t1 = self._parse_hhmm_to_minutes(end_s, 21, 0)
        repeat_min = int(tts_settings.get("budget_boost_repeat_minutes") or 120)
        mo = int(tts_settings.get("budget_boost_minute_offset") or 0)
        slot_minutes = self._iter_budget_boost_slot_minutes(t0, t1, repeat_min, mo)
        now_min = now.hour * 60 + now.minute
        fired = set(self._budget_boost_slots_fired.get(today, []))
        first_run_today = self._budget_boost_scheduled_fired_date != today
        if first_run_today:
            for sm in slot_minutes:
                if sm < now_min:
                    fired.add(sm)
            self._budget_boost_slots_fired[today] = sorted(fired)
            await self._async_save_budget_boost_slots()
            self._budget_boost_scheduled_fired_date = today
        tmpl = (tts_settings.get("budget_boost_scheduled_msg") or "").strip() or DEFAULT_BUDGET_BOOST_SCHEDULED_MSG
        prefix = tts_settings.get("prefix", DEFAULT_TTS_PREFIX)
        weekdays = tts_settings.get("budget_boost_weekdays") or []
        period = self._budget_boost_period_label(weekdays)
        mult = float(tts_settings.get("budget_boost_multiplier") or 2)
        mult_s = self._budget_multiplier_tts_str(max(1.0, min(5.0, mult)))
        vol = float(tts_settings.get("volume", 0.7) or 0.7)
        changed = False
        for sm in slot_minutes:
            if sm > now_min:
                continue
            if sm in fired:
                continue
            if sm == now_min:
                pass
            try:
                message = tmpl.format(
                    prefix=prefix,
                    period_label=period,
                    budget_multiplier=mult_s,
                )
            except (KeyError, ValueError) as e:
                _LOGGER.warning("Budget boost scheduled message format failed: %s", e)
                continue
            try:
                await async_send_tts_or_queue(
                    self.hass,
                    media_player=mp,
                    message=message,
                    language=tts_settings.get("language"),
                    volume=vol,
                    tts_settings=tts_settings,
                    room=None,
                )
            except Exception as e:
                _LOGGER.error("Budget boost scheduled TTS failed: %s", e)
                continue
            fired.add(sm)
            changed = True
        if changed:
            self._budget_boost_slots_fired[today] = sorted(fired)
            await self._async_save_budget_boost_slots()
        self._budget_boost_scheduled_fired_date = today

    def _get_power_entity_ids(self) -> list[str]:
        """Collect all power entity IDs we track for daily energy."""
        entity_ids = []
        for room in self.config_manager.energy_config.get("rooms", []):
            room_id = room.get("id", room["name"].lower().replace(" ", "_"))
            for outlet in room.get("outlets", []):
                if outlet.get("type") == "light":
                    # Lights use tracking key; we track via plug1_entity of light's power
                    # For lights we don't have a sensor - we use the tracking key
                    # State changes come from light entities - but we sum watts from config
                    # Lights: no power entity to listen to; poll adds based on switch state
                    continue
                if outlet.get("plug1_entity"):
                    entity_ids.append(outlet["plug1_entity"])
                if outlet.get("plug2_entity"):
                    entity_ids.append(outlet["plug2_entity"])
        return list(dict.fromkeys(entity_ids))  # Dedupe preserving order

    async def async_start(self) -> None:
        """Start the energy monitoring loop and state-change listeners."""
        if self._running:
            return

        self._running = True
        await self._async_load_budget_boost_slots()
        self._task = asyncio.create_task(self._monitor_loop())

        # Plug energy accumulated via poll loop every second (actual watts read each cycle).
        # State-change was removed: it missed switch current_power_w updates and caused undercounting.
        entity_ids = self._get_power_entity_ids()
        _LOGGER.info("Energy monitor started (poll-based accumulation for %d plug entities)", len(entity_ids))

    async def async_stop(self) -> None:
        """Stop the energy monitoring loop and listeners."""
        self._running = False
        for unsub in self._power_listener_unsub:
            unsub()
        self._power_listener_unsub = []
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        _LOGGER.info("Energy monitor stopped")

    async def _monitor_loop(self) -> None:
        """Main monitoring loop - runs every second."""
        while self._running:
            try:
                await self._check_energy()
            except Exception as e:
                _LOGGER.error("Energy monitor error: %s", e)

            await asyncio.sleep(ENERGY_CHECK_INTERVAL)

    async def _check_energy(self) -> None:
        """Check energy consumption for all rooms and outlets."""
        await self.config_manager.async_snapshot_day_and_reset_if_rolled_over()
        now = dt_util.now()
        today = now.strftime("%Y-%m-%d")
        if self._room_budget_announced_date != today:
            self._room_budget_announced.clear()
            self._room_budget_announced_date = today
        energy_config = self.config_manager.energy_config
        rooms = energy_config.get("rooms", [])
        tts_settings = energy_config.get("tts_settings", {})
        await self._maybe_fire_budget_boost_scheduled(now, today, tts_settings)

        for room in rooms:
            room_id = room.get("id", room["name"].lower().replace(" ", "_"))
            room_name = room["name"]
            room_threshold = room.get("threshold", 0)
            kwh_budget = float(room.get("kwh_budget", 5) or 5)
            media_player = room.get("media_player")
            room_volume = room.get("volume", tts_settings.get("volume", 0.7))

            # Room budget: no warnings/shutoffs until room uses this much today (boost days scale budget)
            room_day_kwh = self.config_manager.get_room_day_kwh(room_id)
            effective_kwh_budget = self._effective_kwh_budget(kwh_budget, now, tts_settings)
            budget_exceeded = effective_kwh_budget <= 0 or room_day_kwh >= effective_kwh_budget

            # TTS when room first exceeds budget (once per day per room)
            if (
                budget_exceeded
                and kwh_budget > 0
                and media_player
                and room_id not in self._room_budget_announced
            ):
                self._room_budget_announced.add(room_id)
                prefix = tts_settings.get("prefix", DEFAULT_TTS_PREFIX)
                msg_template = tts_settings.get("budget_exceeded_msg") or DEFAULT_BUDGET_EXCEEDED_MSG
                try:
                    message = msg_template.format(
                        prefix=prefix,
                        room_name=room_name,
                        kwh_used=spoken_cardinal(round(room_day_kwh)),
                    )
                    await self._async_send_tts_with_lights(
                        room, media_player, message, room_volume, tts_settings
                    )
                except (KeyError, ValueError) as e:
                    _LOGGER.warning("Budget exceeded message format failed for %s: %s", room_name, e)

            # Calculate total room watts and track energy
            room_total_watts = 0.0
            
            for outlet in room.get("outlets", []):
                outlet_name = outlet.get("name", "Outlet")
                outlet_threshold = outlet.get("threshold", 0)
                outlet_total_watts = 0.0

                # Light outlets: when switch on, sum watts from mapped lights and track energy
                if outlet.get("type") == "light":
                    switch_entity = outlet.get("switch_entity")
                    if switch_entity:
                        state = self.hass.states.get(switch_entity)
                        is_on = state is not None and (state.state or "off").lower() in ("on",)
                        if is_on:
                            light_ents = outlet.get("light_entities") or []
                            for le in light_ents:
                                if isinstance(le, dict) and le.get("entity_id", "").startswith("light."):
                                    outlet_total_watts += float(le.get("watts", 0) or 0)
                            if outlet_total_watts > 0:
                                tracking_key = f"light_{room_id}_{(outlet.get('name') or 'light').lower().replace(' ', '_')}"
                                await self.config_manager.async_add_energy_reading(
                                    tracking_key, outlet_total_watts
                                )
                                # Record for intraday 24-hour charts
                                self.config_manager.record_intraday_power(tracking_key, outlet_total_watts)
                    room_total_watts += outlet_total_watts
                    continue

                # Ceiling vent: switch + predefined watts when on
                if outlet.get("type") == "ceiling_vent_fan":
                    switch_entity = outlet.get("switch_entity")
                    watts_when_on = float(outlet.get("watts_when_on", 0) or 0)
                    if switch_entity and watts_when_on > 0:
                        state = self.hass.states.get(switch_entity)
                        is_on = state is not None and (state.state or "off").lower() in ("on",)
                        if is_on:
                            outlet_total_watts = watts_when_on
                            tracking_key = f"ceiling_vent_{room_id}_{(outlet.get('name') or 'vent').lower().replace(' ', '_')}"
                            await self.config_manager.async_add_energy_reading(
                                tracking_key, outlet_total_watts
                            )
                            self.config_manager.record_intraday_power(tracking_key, outlet_total_watts)
                    room_total_watts += outlet_total_watts
                    # Check outlet warning threshold (only when budget exceeded)
                    if budget_exceeded and outlet_threshold > 0 and outlet_total_watts > outlet_threshold:
                        await self._send_outlet_alert(
                            room_id=room_id,
                            room_name=room_name,
                            room=room,
                            outlet_name=outlet_name,
                            current_watts=outlet_total_watts,
                            outlet_threshold=outlet_threshold,
                            media_player=media_player,
                            volume=room_volume,
                            tts_settings=tts_settings,
                        )
                    continue

                # Get plug 1 power (state-change listener handles daily energy accumulation)
                plug1_watts = 0.0
                if outlet.get("plug1_entity"):
                    plug1_watts = self._get_power_value(outlet["plug1_entity"])
                    outlet_total_watts += plug1_watts
                    # Record for intraday 24-hour charts
                    self.config_manager.record_intraday_power(outlet["plug1_entity"], plug1_watts)
                    # Add energy from actual reading (poll every 1s; state_change misses switch power + infrequent sensors)
                    await self.config_manager.async_add_energy_reading(outlet["plug1_entity"], plug1_watts, elapsed_seconds=1.0)

                    # Check plug 1 shutoff threshold (only when budget exceeded)
                    plug1_shutoff = outlet.get("plug1_shutoff", 0)
                    plug1_switch = outlet.get("plug1_switch")
                    if budget_exceeded and plug1_shutoff > 0 and plug1_watts > plug1_shutoff and plug1_switch:
                        await self._handle_plug_shutoff(
                            room_id=room_id,
                            room_name=room_name,
                            room=room,
                            outlet_name=outlet_name,
                            plug_name="Plug 1",
                            switch_entity=plug1_switch,
                            media_player=media_player,
                            volume=room_volume,
                            tts_settings=tts_settings,
                            plug_watts=plug1_watts,
                            plug_shutoff_threshold=int(plug1_shutoff),
                        )

                # Get plug 2 power (state-change listener handles daily energy accumulation)
                plug2_watts = 0.0
                if outlet.get("plug2_entity"):
                    plug2_watts = self._get_power_value(outlet["plug2_entity"])
                    outlet_total_watts += plug2_watts
                    # Record for intraday 24-hour charts
                    self.config_manager.record_intraday_power(outlet["plug2_entity"], plug2_watts)
                    # Add energy from actual reading (poll every 1s)
                    await self.config_manager.async_add_energy_reading(outlet["plug2_entity"], plug2_watts, elapsed_seconds=1.0)

                    # Check plug 2 shutoff threshold (only when budget exceeded)
                    plug2_shutoff = outlet.get("plug2_shutoff", 0)
                    plug2_switch = outlet.get("plug2_switch")
                    if budget_exceeded and plug2_shutoff > 0 and plug2_watts > plug2_shutoff and plug2_switch:
                        await self._handle_plug_shutoff(
                            room_id=room_id,
                            room_name=room_name,
                            room=room,
                            outlet_name=outlet_name,
                            plug_name="Plug 2",
                            switch_entity=plug2_switch,
                            media_player=media_player,
                            volume=room_volume,
                            tts_settings=tts_settings,
                            plug_watts=plug2_watts,
                            plug_shutoff_threshold=int(plug2_shutoff),
                        )

                room_total_watts += outlet_total_watts

                # Check outlet warning threshold (combined plugs, only when budget exceeded)
                if budget_exceeded and outlet_threshold > 0 and outlet_total_watts > outlet_threshold:
                    await self._send_outlet_alert(
                        room_id=room_id,
                        room_name=room_name,
                        room=room,
                        outlet_name=outlet_name,
                        current_watts=outlet_total_watts,
                        outlet_threshold=outlet_threshold,
                        media_player=media_player,
                        volume=room_volume,
                        tts_settings=tts_settings,
                    )

            await self._maybe_restore_minisplit_hold(
                room_id=room_id,
                room_name=room_name,
                room_total_watts=room_total_watts,
                room_threshold=float(room_threshold or 0),
                media_player=media_player,
                volume=room_volume,
                tts_settings=tts_settings,
            )

            # Check room threshold (only when budget exceeded)
            if budget_exceeded and room_threshold > 0 and room_total_watts > room_threshold:
                await self._send_room_alert(
                    room_id=room_id,
                    room_name=room_name,
                    room=room,
                    current_watts=room_total_watts,
                    media_player=media_player,
                    volume=room_volume,
                    tts_settings=tts_settings,
                )

        # Check breaker lines
        await self._check_breaker_lines(tts_settings)

        # Check stove safety
        await self._check_stove_safety(tts_settings)

        # Check power enforcement phase resets and kWh warnings
        await self._check_power_enforcement(tts_settings)

        # Periodically save energy tracking data (every 15 seconds, survives restarts)
        self._save_counter += 1
        if self._save_counter >= 15:
            self._save_counter = 0
            await self.config_manager.async_save_persistent_data()

    def _get_power_value(self, entity_id: str) -> float:
        """Get power value from an entity."""
        state = self.hass.states.get(entity_id)
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

    def _get_room_by_id(self, room_id: str) -> dict | None:
        """Latest room dict from config (by id or slug from name)."""
        for r in self.config_manager.energy_config.get("rooms", []):
            rid = r.get("id", r["name"].lower().replace(" ", "_"))
            if rid == room_id:
                return r
        return None

    def _sum_room_total_watts_only(self, room: dict) -> float:
        """Current room total watts without energy accounting side effects."""
        room_total_watts = 0.0
        for outlet in room.get("outlets", []):
            outlet_total_watts = 0.0
            if outlet.get("type") == "light":
                switch_entity = outlet.get("switch_entity")
                if switch_entity:
                    state = self.hass.states.get(switch_entity)
                    is_on = state is not None and (state.state or "off").lower() in ("on",)
                    if is_on:
                        for le in outlet.get("light_entities") or []:
                            if isinstance(le, dict) and le.get("entity_id", "").startswith("light."):
                                outlet_total_watts += float(le.get("watts", 0) or 0)
                room_total_watts += outlet_total_watts
                continue
            if outlet.get("type") == "ceiling_vent_fan":
                switch_entity = outlet.get("switch_entity")
                watts_when_on = float(outlet.get("watts_when_on", 0) or 0)
                if switch_entity and watts_when_on > 0:
                    state = self.hass.states.get(switch_entity)
                    is_on = state is not None and (state.state or "off").lower() in ("on",)
                    if is_on:
                        outlet_total_watts = watts_when_on
                room_total_watts += outlet_total_watts
                continue
            if outlet.get("plug1_entity"):
                outlet_total_watts += self._get_power_value(outlet["plug1_entity"])
            if outlet.get("plug2_entity"):
                outlet_total_watts += self._get_power_value(outlet["plug2_entity"])
            room_total_watts += outlet_total_watts
        return room_total_watts

    def _select_minisplit_enforcement_target(
        self, room: dict, current_watts: float, room_threshold: float
    ) -> dict | None:
        """Pick one minisplit outlet if it can clear the room threshold when turned off."""
        thr = float(room_threshold or 0)
        if thr <= 0:
            return None
        best: dict | None = None
        best_w = -1.0
        for outlet in room.get("outlets", []):
            if outlet.get("type") != "minisplit":
                continue
            sw = outlet.get("plug1_switch")
            if not sw or not str(sw).startswith("switch."):
                continue
            state = self.hass.states.get(sw)
            is_on = state is not None and (state.state or "off").lower() in ("on",)
            if not is_on:
                continue
            plug_ent = outlet.get("plug1_entity")
            w = self._get_power_value(plug_ent) if plug_ent else 0.0
            min_w = int(outlet.get("minisplit_enforcement_min_watts", 0) or 0)
            if min_w > 0 and w < min_w:
                continue
            if current_watts - w > thr:
                continue
            if w > best_w:
                best_w = w
                best = outlet
        return best

    def _format_minisplit_phase2_warn(
        self,
        tts_settings: dict,
        prefix: str,
        room_name: str,
        ms_outlet: dict,
        warning_count: int,
        room_threshold: float | int,
    ) -> str:
        tmpl = (tts_settings.get("minisplit_phase2_warn_msg") or "").strip()
        if not tmpl:
            tmpl = DEFAULT_MINISPLIT_PHASE2_WARN_MSG
        off_sec = int(ms_outlet.get("minisplit_enforcement_off_seconds", 60) or 60)
        try:
            return tmpl.format(
                prefix=prefix,
                room_name=room_name,
                outlet_name=ms_outlet.get("name") or "Mini-split",
                warning_count=warning_count,
                restore_delay=spoken_cardinal(off_sec),
                room_threshold=spoken_cardinal(int(room_threshold or 0)),
            )
        except (KeyError, ValueError):
            return ""

    async def _maybe_restore_minisplit_hold(
        self,
        room_id: str,
        room_name: str,
        room_total_watts: float,
        room_threshold: float,
        media_player: str | None,
        volume: float,
        tts_settings: dict,
    ) -> None:
        """Turn held mini-split(s) back on when room total is at or under threshold."""
        if room_id not in self._minisplit_hold:
            return
        if room_threshold <= 0:
            return
        if room_total_watts > room_threshold:
            return
        hold = self._minisplit_hold.pop(room_id)
        switches = hold.get("switches") or set()
        outlet_name = hold.get("outlet_name") or "Mini-split"
        eff_vol = float(hold.get("volume", volume))
        prefix = tts_settings.get("prefix", DEFAULT_TTS_PREFIX)
        try:
            for sw in switches:
                if sw and str(sw).startswith("switch."):
                    await self.hass.services.async_call(
                        "switch", "turn_on", {"entity_id": sw}, blocking=True
                    )
            _LOGGER.info(
                "Minisplit hold released (room under threshold): %s switches=%s",
                room_id,
                switches,
            )
        except Exception as e:
            _LOGGER.error("Minisplit hold restore failed: %s", e)
            return
        rest_tmpl = (tts_settings.get("minisplit_phase2_restore_msg") or "").strip()
        if not media_player or not rest_tmpl:
            return
        try:
            rmsg = rest_tmpl.format(
                prefix=prefix,
                room_name=room_name,
                outlet_name=outlet_name,
                room_threshold=spoken_cardinal(int(room_threshold)),
            )
            await async_send_tts_or_queue(
                self.hass,
                media_player=media_player,
                message=rmsg,
                language=tts_settings.get("language"),
                volume=eff_vol,
                tts_settings=tts_settings,
            )
        except (KeyError, ValueError) as e:
            _LOGGER.warning("Minisplit restore TTS format failed: %s", e)

    async def _run_phase2_minisplit_enforcement(
        self,
        room_id: str,
        room_name: str,
        room: dict,
        ms_outlet: dict,
        media_player: str | None,
        volume: float,
        tts_settings: dict,
        prefix: str,
        phase2_delay: int,
        *,
        cycle_log_extra: dict | None = None,
    ) -> None:
        """Minisplit-first phase-2: off, min wait, optional excluded full-room cycle, conditional restore."""
        sw = ms_outlet.get("plug1_switch")
        if not sw or not str(sw).startswith("switch."):
            await self._power_cycle_room_outlets(
                room_id, room, phase2_delay, log_extra=cycle_log_extra
            )
            return

        off_sec = int(ms_outlet.get("minisplit_enforcement_off_seconds", 60) or 60)
        outlet_name = ms_outlet.get("name") or "Mini-split"
        room_name_log = str(room.get("name") or room_id)

        try:
            merged_cycle = {**(cycle_log_extra or {})}
            merged_cycle["outlets_cycled"] = 1
            await self.config_manager.async_record_power_cycle_initiated(
                room_id, room_name_log, extra=merged_cycle
            )
            await self.hass.services.async_call(
                "switch", "turn_off", {"entity_id": sw}, blocking=True
            )
            _LOGGER.warning(
                "Phase-2 minisplit enforcement: turned off %s in %s",
                sw,
                room_id,
            )
            if room_id in self._minisplit_hold:
                self._minisplit_hold[room_id]["switches"].add(sw)
            else:
                self._minisplit_hold[room_id] = {
                    "switches": {sw},
                    "outlet_name": outlet_name,
                    "volume": volume,
                }

            await asyncio.sleep(off_sec)

            room_live = self._get_room_by_id(room_id) or room
            total = self._sum_room_total_watts_only(room_live)
            thr = float(room_live.get("threshold") or 0)
            hold_sw = frozenset(
                self._minisplit_hold.get(room_id, {}).get("switches", set())
            )
            if total > thr and hold_sw:
                await self._power_cycle_room_outlets(
                    room_id,
                    room_live,
                    phase2_delay,
                    exclude_switch_entities=hold_sw,
                    record_cycle=False,
                )

            hold_oname = self._minisplit_hold.get(room_id, {}).get(
                "outlet_name", outlet_name
            )
            after_tmpl = (tts_settings.get("minisplit_phase2_after_msg") or "").strip()
            if not after_tmpl:
                after_tmpl = (tts_settings.get("phase2_after_msg") or "").strip()
            if not after_tmpl:
                after_tmpl = DEFAULT_MINISPLIT_PHASE2_AFTER_MSG
            if media_player:
                try:
                    after_msg = after_tmpl.format(
                        prefix=prefix,
                        room_name=room_name,
                        outlet_name=hold_oname,
                        room_threshold=spoken_cardinal(int(thr)),
                    )
                except (KeyError, ValueError):
                    after_msg = ""
                if after_msg:
                    await async_send_tts_or_queue(
                        self.hass,
                        media_player=media_player,
                        message=after_msg,
                        language=tts_settings.get("language"),
                        volume=volume,
                        tts_settings=tts_settings,
                    )

            room_live = self._get_room_by_id(room_id) or room_live
            total = self._sum_room_total_watts_only(room_live)
            thr = float(room_live.get("threshold") or 0)
            if room_id in self._minisplit_hold and thr > 0 and total <= thr:
                hold = self._minisplit_hold.pop(room_id)
                for s in hold.get("switches", set()):
                    if s and str(s).startswith("switch."):
                        await self.hass.services.async_call(
                            "switch", "turn_on", {"entity_id": s}, blocking=True
                        )
                rest_tmpl = (tts_settings.get("minisplit_phase2_restore_msg") or "").strip()
                if media_player and rest_tmpl:
                    try:
                        rmsg = rest_tmpl.format(
                            prefix=prefix,
                            room_name=room_name,
                            outlet_name=hold.get("outlet_name", outlet_name),
                            room_threshold=spoken_cardinal(int(thr)),
                        )
                        await async_send_tts_or_queue(
                            self.hass,
                            media_player=media_player,
                            message=rmsg,
                            language=tts_settings.get("language"),
                            volume=volume,
                            tts_settings=tts_settings,
                        )
                    except (KeyError, ValueError) as e:
                        _LOGGER.warning("Minisplit immediate restore TTS failed: %s", e)
        except Exception as e:
            _LOGGER.error("Phase-2 minisplit enforcement failed: %s", e)

    async def _handle_plug_shutoff(
        self,
        room_id: str,
        room_name: str,
        room: dict,
        outlet_name: str,
        plug_name: str,
        switch_entity: str,
        media_player: str | None,
        volume: float,
        tts_settings: dict,
        *,
        plug_watts: float | None = None,
        plug_shutoff_threshold: int | None = None,
    ) -> None:
        """Handle plug shutoff when threshold exceeded - turn off, wait 5s, turn back on."""
        shutoff_key = f"{room_id}_{outlet_name}_{plug_name}"
        
        # Don't re-trigger if already in shutoff cycle
        if self._shutoff_pending.get(shutoff_key):
            return
        
        self._shutoff_pending[shutoff_key] = True
        
        try:
            # Turn off the switch
            await self.hass.services.async_call(
                "switch", "turn_off",
                {"entity_id": switch_entity},
                blocking=True,
            )
            _LOGGER.warning(
                "Plug shutoff triggered: %s %s %s",
                room_name, outlet_name, plug_name,
            )
            
            # Send TTS message (with optional responsive light loop)
            if media_player:
                prefix = tts_settings.get("prefix", DEFAULT_TTS_PREFIX)
                msg_template = tts_settings.get("shutoff_msg", DEFAULT_SHUTOFF_MSG)
                message = msg_template.format(
                    prefix=prefix,
                    room_name=room_name,
                    outlet_name=outlet_name,
                    plug=plug_name,
                )
                room_live = self._get_room_by_id(room_id) or room
                room_sum = self._sum_room_total_watts_only(room_live)
                shutoff_extra: dict = {
                    "tts_message": message,
                    "volume_percent": int(round(volume * 100)),
                    "room_watts": int(round(room_sum)),
                }
                if plug_watts is not None:
                    shutoff_extra["outlet_watts"] = int(round(plug_watts))
                if plug_shutoff_threshold is not None:
                    shutoff_extra["outlet_threshold"] = int(plug_shutoff_threshold)
                try:
                    await self._async_send_tts_with_lights(
                        room, media_player, message, volume, tts_settings
                    )
                    # Count only when TTS was actually sent
                    await self.config_manager.async_increment_shutoff(room_id)
                    await self.config_manager.async_add_event_log_entry(
                        room_id,
                        room_name,
                        "shutoff",
                        outlet_name,
                        True,
                        extra=shutoff_extra,
                    )
                except Exception as tts_err:
                    _LOGGER.error("Shutoff TTS error: %s", tts_err)
                    await self.config_manager.async_add_event_log_entry(
                        room_id,
                        room_name,
                        "shutoff",
                        outlet_name,
                        False,
                        extra=shutoff_extra,
                    )
            
            # Wait 5 seconds
            await asyncio.sleep(SHUTOFF_RESET_DELAY)
            
            # Turn back on
            await self.hass.services.async_call(
                "switch", "turn_on",
                {"entity_id": switch_entity},
                blocking=True,
            )
            _LOGGER.info(
                "Plug reset after shutoff: %s %s %s",
                room_name, outlet_name, plug_name,
            )
        except Exception as e:
            _LOGGER.error("Plug shutoff error: %s", e)
        finally:
            self._shutoff_pending[shutoff_key] = False

    def _get_wrgb_light_entities(self, room: dict) -> list[str]:
        """Get all WRGB light entity IDs for a room."""
        entities: list[str] = []
        for outlet in room.get("outlets", []):
            if outlet.get("type") != "light":
                continue
            for le in outlet.get("light_entities") or []:
                if isinstance(le, dict) and le.get("wrgb") and le.get("entity_id", "").startswith("light."):
                    entities.append(le["entity_id"])
        return list(dict.fromkeys(entities))

    def _get_light_restore_data(self, entity_ids: list[str]) -> dict[str, dict]:
        """Get current light state for restore after warning loop.
        Stores only the mode-appropriate attribute: RGB mode -> rgb_color,
        temp mode -> color_temp_kelvin. Never both (one restore call per light)."""
        restore: dict[str, dict] = {}
        for eid in entity_ids:
            state = self.hass.states.get(eid)
            if state is None:
                continue
            attrs = state.attributes or {}
            is_on = (state.state or "off").lower() == "on"
            data: dict = {"was_on": is_on}
            color_mode = (attrs.get("color_mode") or "").lower()
            # RGB mode: store rgb_color only
            if color_mode in ("rgb", "hs", "xy") and "rgb_color" in attrs:
                data["rgb_color"] = list(attrs["rgb_color"])
            # Temp mode: store color_temp_kelvin or color_temp only
            elif color_mode == "color_temp":
                if "color_temp_kelvin" in attrs:
                    data["color_temp_kelvin"] = attrs["color_temp_kelvin"]
                elif "color_temp" in attrs:
                    data["color_temp"] = attrs["color_temp"]
            # Fallback when color_mode missing: prefer rgb if present, else temp
            elif "rgb_color" in attrs:
                data["rgb_color"] = list(attrs["rgb_color"])
            elif "color_temp_kelvin" in attrs:
                data["color_temp_kelvin"] = attrs["color_temp_kelvin"]
            elif "color_temp" in attrs:
                data["color_temp"] = attrs["color_temp"]
            restore[eid] = data
        return restore

    async def _async_light_warning_loop(
        self,
        entity_ids: list[str],
        rgb_color: list[int],
        temp_kelvin: int,
        tts_task: asyncio.Task,
        interval: float = 1.5,
    ) -> None:
        """Loop light color/temp changes until TTS task completes."""
        try:
            while not tts_task.done():
                await self.hass.services.async_call(
                    "light",
                    "turn_on",
                    {"entity_id": entity_ids, "rgb_color": rgb_color},
                    blocking=True,
                )
                await asyncio.sleep(interval)
                if tts_task.done():
                    break
                await self.hass.services.async_call(
                    "light",
                    "turn_on",
                    {"entity_id": entity_ids, "color_temp_kelvin": temp_kelvin},
                    blocking=True,
                )
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            _LOGGER.error("Light warning loop error: %s", e)

    async def _async_restore_lights(
        self,
        entity_ids: list[str],
        restore_data: dict[str, dict],
    ) -> None:
        """Restore lights to their pre-warning state."""
        for eid in entity_ids:
            data = restore_data.get(eid)
            if not data:
                continue
            try:
                was_on = data.get("was_on", True)
                if not was_on:
                    await self.hass.services.async_call(
                        "light", "turn_off", {"entity_id": eid}, blocking=True
                    )
                    continue
                # Restore color/temp for lights that were on
                restore_attrs = {k: v for k, v in data.items() if k != "was_on" and v is not None}
                await self.hass.services.async_call(
                    "light",
                    "turn_on",
                    {"entity_id": eid, **restore_attrs} if restore_attrs else {"entity_id": eid},
                    blocking=True,
                )
            except Exception as e:
                _LOGGER.warning("Failed to restore light %s: %s", eid, e)

    async def _async_send_tts_with_lights(
        self,
        room: dict,
        media_player: str | None,
        message: str,
        volume: float,
        tts_settings: dict,
        post_send_callback=None,
    ) -> None:
        """Send TTS and optionally run responsive light loop. Waits for media player ready (on/idle/standby).
        post_send_callback runs after TTS is actually sent (incl. when dequeued from queue)."""
        if not media_player:
            return

        async def _do_lights_and_tts() -> None:
            wrgb_lights = self._get_wrgb_light_entities(room) if room.get("responsive_light_warnings") else []
            rgb = room.get("responsive_light_color") or [245, 0, 0]
            temp_k = int(room.get("responsive_light_temp", 6500))
            interval = float(room.get("responsive_light_interval", 1.5))
            if wrgb_lights:
                restore_data = self._get_light_restore_data(wrgb_lights)
                tts_task = asyncio.create_task(
                    async_send_tts(
                        self.hass,
                        media_player=media_player,
                        message=message,
                        language=tts_settings.get("language"),
                        volume=volume,
                    )
                )
                light_task = asyncio.create_task(
                    self._async_light_warning_loop(wrgb_lights, rgb, temp_k, tts_task, interval)
                )
                await asyncio.gather(tts_task, light_task)
                await self._async_restore_lights(wrgb_lights, restore_data)
            else:
                await async_send_tts(
                    self.hass,
                    media_player=media_player,
                    message=message,
                    language=tts_settings.get("language"),
                    volume=volume,
                )

        await async_send_tts_or_queue(
            self.hass,
            media_player=media_player,
            message=message,
            language=tts_settings.get("language"),
            volume=volume,
            tts_settings=tts_settings,
            room=room,
            with_lights_callback=_do_lights_and_tts,
            post_send_callback=post_send_callback,
        )

    def _get_room_for_breaker(self, breaker_id: str) -> dict | None:
        """Get first room with responsive lights and outlets on this breaker."""
        outlets = self.config_manager.get_outlets_for_breaker(breaker_id)
        room_ids = list(dict.fromkeys(o["room_id"] for o in outlets))
        for room in self.config_manager.energy_config.get("rooms", []):
            if room.get("id") in room_ids and room.get("responsive_light_warnings"):
                if self._get_wrgb_light_entities(room):
                    return room
        return None

    async def _send_room_alert(
        self,
        room_id: str,
        room_name: str,
        room: dict,
        current_watts: float,
        media_player: str | None,
        volume: float,
        tts_settings: dict,
    ) -> None:
        """Send TTS alert for room threshold exceeded with power enforcement."""
        if not media_player:
            return

        # Record threshold warning first (needed for phase transition check)
        await self.config_manager.async_record_threshold_warning(room_id, current_watts)

        # Check if we're transitioning to phase 1 or 2 (we always need TTS for phase escalation)
        now = dt_util.now()
        pe = self.config_manager.energy_config.get("power_enforcement", {})
        enforcement_enabled = self.config_manager.is_room_enforcement_enabled(room_id)
        phase1_enabled = pe.get("phase1_enabled", True)
        phase2_enabled = pe.get("phase2_enabled", True)
        phase_transition = False
        if enforcement_enabled:
            state = self.config_manager.get_enforcement_state(room_id)
            phase = int(state.get("phase", 0) or 0)
            phase1_count = pe.get("phase1_warning_count", 20)
            phase1_window = pe.get("phase1_time_window_minutes", 60)
            phase2_count = pe.get("phase2_warning_count", 40)
            phase2_window = pe.get("phase2_time_window_minutes", 30)
            warnings_p1 = self.config_manager.get_warnings_in_window(room_id, phase1_window)
            warnings_p2 = self.config_manager.get_warnings_in_window(room_id, phase2_window)
            phase_transition = (
                (phase2_enabled and warnings_p2 >= phase2_count and phase < 2) or
                (phase1_enabled and warnings_p1 >= phase1_count and phase < 1)
            )

        # Cooldown: skip for phase transitions (we always need TTS when phases enable)
        last_alert = self._last_room_alerts.get(room_id)
        if not phase_transition and last_alert and (now - last_alert).total_seconds() < ALERT_COOLDOWN:
            return  # Still in cooldown

        self._last_room_alerts[room_id] = now

        # Get power enforcement settings
        pe = self.config_manager.energy_config.get("power_enforcement", {})
        enforcement_enabled = self.config_manager.is_room_enforcement_enabled(room_id)
        room_threshold = room.get("threshold", 0)

        # Calculate effective volume (base + enforcement offset)
        effective_volume = volume
        message = ""
        prefix = tts_settings.get("prefix", DEFAULT_TTS_PREFIX)

        if enforcement_enabled:
            state = self.config_manager.get_enforcement_state(room_id)
            phase1_count = pe.get("phase1_warning_count", 20)
            phase1_window = pe.get("phase1_time_window_minutes", 60)
            phase2_count = pe.get("phase2_warning_count", 40)
            phase2_window = pe.get("phase2_time_window_minutes", 30)
            volume_increment = pe.get("phase1_volume_increment", 2)

            warnings_in_phase1_window = self.config_manager.get_warnings_in_window(room_id, phase1_window)
            warnings_in_phase2_window = self.config_manager.get_warnings_in_window(room_id, phase2_window)

            # Coerce phase to int (JSON load can occasionally yield float)
            phase = int(state.get("phase", 0) or 0)

            # Check for phase 2 (power cycling) - set message; power cycle happens AFTER TTS
            if phase2_enabled and warnings_in_phase2_window >= phase2_count and phase < 2:
                await self.config_manager.async_set_enforcement_phase(room_id, 2)
                ms_o = self._select_minisplit_enforcement_target(
                    room, float(current_watts), float(room_threshold or 0)
                )
                if ms_o:
                    message = self._format_minisplit_phase2_warn(
                        tts_settings,
                        prefix,
                        room_name,
                        ms_o,
                        warnings_in_phase2_window,
                        room_threshold,
                    )
                if not message:
                    msg_template = tts_settings.get("phase2_warn_msg") or ""
                    try:
                        message = msg_template.format(
                            prefix=prefix,
                            room_name=room_name,
                            warning_count=warnings_in_phase2_window,
                        )
                    except (KeyError, ValueError):
                        message = ""

            # Check for phase 1 (volume escalation)
            elif phase1_enabled and warnings_in_phase1_window >= phase1_count and phase < 1:
                await self.config_manager.async_set_enforcement_phase(room_id, 1)
                now_p1 = dt_util.now()
                boost_tmpl = (tts_settings.get("phase1_warn_msg_boost_day") or "").strip()
                if self._is_budget_boost_day(now_p1, tts_settings) and boost_tmpl:
                    base_b = float(room.get("kwh_budget", 5) or 5)
                    eff_b = self._effective_kwh_budget(base_b, now_p1, tts_settings)
                    mult = float(tts_settings.get("budget_boost_multiplier") or 2)
                    mult_s = self._budget_multiplier_tts_str(max(1.0, min(5.0, mult)))
                    weekdays = tts_settings.get("budget_boost_weekdays") or []
                    period = self._budget_boost_period_label(weekdays)
                    try:
                        message = boost_tmpl.format(
                            prefix=prefix,
                            room_name=room_name,
                            warning_count=spoken_cardinal(warnings_in_phase1_window),
                            threshold=spoken_cardinal(
                                int(room_threshold) if room_threshold is not None else 0
                            ),
                            kwh_budget=spoken_cardinal(round(base_b)),
                            kwh_budget_effective=spoken_cardinal(round(eff_b)),
                            budget_multiplier=mult_s,
                            period_label=period,
                        )
                    except (KeyError, ValueError):
                        message = ""
                else:
                    message = ""
                if not message:
                    msg_template = tts_settings.get("phase1_warn_msg") or ""
                    try:
                        message = msg_template.format(
                            prefix=prefix,
                            room_name=room_name,
                            warning_count=spoken_cardinal(warnings_in_phase1_window),
                            threshold=spoken_cardinal(
                                int(room_threshold) if room_threshold is not None else 0
                            ),
                        )
                    except (KeyError, ValueError):
                        message = ""

            # Already phase 2: use minisplit or generic phase-2 warn when repeating
            phase = int(self.config_manager.get_enforcement_state(room_id).get("phase", 0) or 0)
            if (
                enforcement_enabled
                and phase2_enabled
                and phase >= 2
                and warnings_in_phase2_window >= phase2_count
                and not message
            ):
                ms_o = self._select_minisplit_enforcement_target(
                    room, float(current_watts), float(room_threshold or 0)
                )
                if ms_o:
                    message = self._format_minisplit_phase2_warn(
                        tts_settings,
                        prefix,
                        room_name,
                        ms_o,
                        warnings_in_phase2_window,
                        room_threshold,
                    )
                if not message:
                    msg_template = tts_settings.get("phase2_warn_msg") or ""
                    try:
                        message = msg_template.format(
                            prefix=prefix,
                            room_name=room_name,
                            warning_count=warnings_in_phase2_window,
                        )
                    except (KeyError, ValueError):
                        message = ""

            # If in phase 1+, increase volume (re-fetch phase after possible phase change)
            phase = int(self.config_manager.get_enforcement_state(room_id).get("phase", 0) or 0)
            if phase >= 1:
                new_offset = await self.config_manager.async_increment_volume_offset(room_id, volume_increment)
                effective_volume = min(1.0, volume + (new_offset / 100.0))
            # Phase 2: cap volume at phase2_max_volume (0-100 scale)
            if phase >= 2:
                phase2_max = pe.get("phase2_max_volume", 100)
                if phase2_max is not None:
                    cap = max(0.0, min(1.0, float(phase2_max) / 100.0))
                    effective_volume = min(effective_volume, cap)

            # Phase 2 power cycling moved to post_send_callback (runs after TTS actually plays)

        # Use standard message if no enforcement message was set (or format failed)
        if not message:
            msg_template = tts_settings.get("room_warn_msg") or DEFAULT_ROOM_WARN_MSG
            try:
                message = msg_template.format(
                    prefix=prefix,
                    room_name=room_name,
                    watts=int(current_watts),
                    threshold=int(room_threshold) if room_threshold is not None else 0,
                )
            except (KeyError, ValueError):
                message = f"{prefix} {room_name} is using {int(current_watts)} watts out of {int(room_threshold or 0)} watt room threshold, reduce your usage."

        # Power cycle runs in post_send_callback after TTS actually plays (incl. when queued).
        # Flow: TTS (before) -> power cycle ALL outlets -> TTS (after, adhere message)
        post_send_cb = None
        if enforcement_enabled and phase2_enabled:
            phase_now = int(self.config_manager.get_enforcement_state(room_id).get("phase", 0) or 0)
            if phase_now == 2:
                delay_sec = pe.get("phase2_cycle_delay_seconds", 5)
                after_template = tts_settings.get("phase2_after_msg") or ""
                ms_target = self._select_minisplit_enforcement_target(
                    room, float(current_watts), float(room_threshold or 0)
                )

                try:
                    rtc = int(room.get("threshold", 0) or 0)
                except (TypeError, ValueError):
                    rtc = 0
                cycle_log_extra = {
                    "tts_message": message,
                    "room_watts": int(round(current_watts)),
                    "room_threshold": rtc,
                    "enforcement_phase": phase_now,
                    "volume_percent": int(round(effective_volume * 100)),
                }

                async def _power_cycle_and_tts_after() -> None:
                    if ms_target:
                        await self._run_phase2_minisplit_enforcement(
                            room_id,
                            room_name,
                            room,
                            ms_target,
                            media_player,
                            effective_volume,
                            tts_settings,
                            prefix,
                            delay_sec,
                            cycle_log_extra=cycle_log_extra,
                        )
                    else:
                        await self._power_cycle_room_outlets(
                            room_id, room, delay_sec, log_extra=cycle_log_extra
                        )
                        if media_player and after_template:
                            try:
                                after_msg = after_template.format(
                                    prefix=prefix,
                                    room_name=room_name,
                                )
                            except (KeyError, ValueError):
                                after_msg = (
                                    f"{prefix} Cycle complete in {room_name}. "
                                    "Stay under limit or outlets cycle again."
                                )
                            await async_send_tts_or_queue(
                                self.hass,
                                media_player=media_player,
                                message=after_msg,
                                language=tts_settings.get("language"),
                                volume=effective_volume,
                                tts_settings=tts_settings,
                            )

                post_send_cb = _power_cycle_and_tts_after

        try:
            rt_raw = room.get("threshold", 0)
            try:
                rt_int = int(rt_raw) if rt_raw is not None else 0
            except (TypeError, ValueError):
                rt_int = 0

            def _room_warning_log_extra() -> dict:
                ex: dict = {
                    "tts_message": message,
                    "room_watts": int(round(current_watts)),
                    "room_threshold": rt_int,
                    "volume_percent": int(round(effective_volume * 100)),
                }
                if enforcement_enabled:
                    ex["enforcement_phase"] = int(
                        self.config_manager.get_enforcement_state(room_id).get(
                            "phase", 0
                        )
                        or 0
                    )
                return ex

            await self._async_send_tts_with_lights(
                room, media_player, message, effective_volume, tts_settings,
                post_send_callback=post_send_cb,
            )
            # Count only when TTS was actually sent
            await self.config_manager.async_increment_warning(room_id)
            await self.config_manager.async_add_event_log_entry(
                room_id,
                room_name,
                "warning",
                None,
                True,
                extra=_room_warning_log_extra(),
            )
            _LOGGER.warning(
                "Room threshold alert: %s - %dW (enforcement phase %d, volume %.0f%%)",
                room_name,
                int(current_watts),
                self.config_manager.get_enforcement_state(room_id).get("phase", 0) if enforcement_enabled else 0,
                effective_volume * 100,
            )
        except Exception as e:
            _LOGGER.error("Failed to send room threshold alert: %s", e)
            try:
                rt_raw = room.get("threshold", 0)
                rt_int = int(rt_raw) if rt_raw is not None else 0
            except (TypeError, ValueError):
                rt_int = 0
            fail_ex: dict = {
                "tts_message": message,
                "room_watts": int(round(current_watts)),
                "room_threshold": rt_int,
                "volume_percent": int(round(effective_volume * 100)),
            }
            if enforcement_enabled:
                fail_ex["enforcement_phase"] = int(
                    self.config_manager.get_enforcement_state(room_id).get("phase", 0)
                    or 0
                )
            await self.config_manager.async_add_event_log_entry(
                room_id,
                room_name,
                "warning",
                None,
                False,
                extra=fail_ex,
            )

    async def _power_cycle_room_outlets(
        self,
        room_id: str,
        room: dict,
        delay_seconds: int,
        *,
        exclude_switch_entities: frozenset[str] | None = None,
        record_cycle: bool = True,
        log_extra: dict | None = None,
    ) -> None:
        """Power cycle outlets with switches (stove/microwave excluded for safety)."""
        exclude = exclude_switch_entities or frozenset()
        switch_entities: list[str] = []
        seen: set[str] = set()
        for outlet in room.get("outlets", []):
            if outlet.get("type") in ("stove", "microwave"):
                continue
            for switch in (
                outlet.get("plug1_switch"),
                outlet.get("plug2_switch"),
                outlet.get("switch_entity"),
            ):
                if (
                    switch
                    and switch.startswith("switch.")
                    and switch not in seen
                    and switch not in exclude
                ):
                    seen.add(switch)
                    switch_entities.append(switch)

        if not switch_entities:
            _LOGGER.debug(
                "No switchable outlets in room %s for power cycle (after exclusions)",
                room_id,
            )
            return

        try:
            room_name = str(room.get("name") or room_id)
            if record_cycle:
                merged = {**(log_extra or {})}
                merged["outlets_cycled"] = len(switch_entities)
                await self.config_manager.async_record_power_cycle_initiated(
                    room_id, room_name, extra=merged
                )
            _LOGGER.info(
                "Power cycling %d outlets in %s for enforcement",
                len(switch_entities),
                room_id,
            )
            await self.hass.services.async_call(
                "switch", "turn_off", {"entity_id": switch_entities}, blocking=True
            )
            await asyncio.sleep(delay_seconds)
            await self.hass.services.async_call(
                "switch", "turn_on", {"entity_id": switch_entities}, blocking=True
            )
            _LOGGER.warning(
                "Power cycled %d outlets in %s for enforcement",
                len(switch_entities),
                room_id,
            )
        except Exception as e:
            _LOGGER.error("Failed to power cycle outlets in %s: %s", room_id, e)

    async def _send_outlet_alert(
        self,
        room_id: str,
        room_name: str,
        room: dict,
        outlet_name: str,
        current_watts: float,
        outlet_threshold: int,
        media_player: str | None,
        volume: float,
        tts_settings: dict,
    ) -> None:
        """Send TTS alert for outlet threshold exceeded."""
        if not media_player:
            return

        # Check cooldown - use combined room+outlet key
        alert_key = f"{room_id}_{outlet_name}"
        now = dt_util.now()
        last_alert = self._last_outlet_alerts.get(alert_key)
        if last_alert and (now - last_alert).total_seconds() < ALERT_COOLDOWN:
            return  # Still in cooldown

        # Update last alert time
        self._last_outlet_alerts[alert_key] = now

        # Record threshold warning for power enforcement (outlet warnings count toward room)
        await self.config_manager.async_record_threshold_warning(room_id, current_watts)

        # Format message with prefix
        prefix = tts_settings.get("prefix", DEFAULT_TTS_PREFIX)
        msg_template = tts_settings.get("outlet_warn_msg", DEFAULT_OUTLET_WARN_MSG)
        message = msg_template.format(
            prefix=prefix,
            room_name=room_name,
            outlet_name=outlet_name,
            watts=spoken_cardinal(current_watts),
            threshold=spoken_cardinal(outlet_threshold),
        )

        room_sum = self._sum_room_total_watts_only(room)

        def _outlet_warning_extra() -> dict:
            ox: dict = {
                "tts_message": message,
                "outlet_watts": int(round(current_watts)),
                "outlet_threshold": int(outlet_threshold),
                "room_watts": int(round(room_sum)),
                "volume_percent": int(round(volume * 100)),
            }
            if self.config_manager.is_room_enforcement_enabled(room_id):
                ox["enforcement_phase"] = int(
                    self.config_manager.get_enforcement_state(room_id).get("phase", 0)
                    or 0
                )
            return ox

        try:
            await self._async_send_tts_with_lights(
                room, media_player, message, volume, tts_settings
            )
            # Count only when TTS was actually sent
            await self.config_manager.async_increment_warning(room_id)
            await self.config_manager.async_add_event_log_entry(
                room_id,
                room_name,
                "warning",
                outlet_name,
                True,
                extra=_outlet_warning_extra(),
            )
            _LOGGER.warning(
                "Outlet threshold alert: %s %s - %dW",
                room_name,
                outlet_name,
                int(current_watts),
            )
        except Exception as e:
            _LOGGER.error("Failed to send outlet threshold alert: %s", e)
            await self.config_manager.async_add_event_log_entry(
                room_id,
                room_name,
                "warning",
                outlet_name,
                False,
                extra=_outlet_warning_extra(),
            )

    async def _check_power_enforcement(self, tts_settings: dict) -> None:
        """Check power enforcement phase resets and kWh warnings."""
        pe = self.config_manager.energy_config.get("power_enforcement", {})
        if not pe.get("enabled", False):
            return

        prefix = tts_settings.get("prefix", DEFAULT_TTS_PREFIX)
        rooms = self.config_manager.energy_config.get("rooms", [])
        rooms_enabled = pe.get("rooms_enabled", [])

        # Check phase resets for each room
        phase1_reset = pe.get("phase1_reset_minutes", 60)
        phase2_reset = pe.get("phase2_reset_minutes", 30)

        for room in rooms:
            room_id = room.get("id", room["name"].lower().replace(" ", "_"))
            room_name = room.get("name", room_id)
            media_player = room.get("media_player")
            volume = float(room.get("volume", 0.7))

            if room_id not in rooms_enabled:
                continue

            state = self.config_manager.get_enforcement_state(room_id)
            current_phase = state.get("phase", 0)

            # Check for phase reset (no warnings for reset_minutes)
            reset_minutes = phase2_reset if current_phase == 2 else phase1_reset
            if current_phase > 0 and self.config_manager.check_phase_reset(room_id, reset_minutes):
                await self.config_manager.async_set_enforcement_phase(room_id, 0)
                msg_template = tts_settings.get("phase_reset_msg", "")
                if msg_template and media_player:
                    message = msg_template.format(
                        prefix=prefix,
                        room_name=room_name,
                    )
                    try:
                        await self._async_send_tts_with_lights(
                            room, media_player, message, volume, tts_settings
                        )
                        _LOGGER.info("Power enforcement reset for %s", room_name)
                    except Exception as e:
                        _LOGGER.error("Failed to send phase reset TTS: %s", e)

            # Check room kWh intervals
            intervals = pe.get("room_kwh_intervals", [5, 10, 15, 20])
            interval_hit = await self.config_manager.async_should_send_room_kwh_alert(room_id, intervals)
            if interval_hit is not None and media_player:
                percentage = self.config_manager.get_room_percentage_of_total(room_id)
                msg_template = tts_settings.get("room_kwh_warn_msg", "")
                if msg_template:
                    message = msg_template.format(
                        prefix=prefix,
                        room_name=room_name,
                        kwh_limit=interval_hit,
                        percentage=percentage,
                    )
                    try:
                        await self._async_send_tts_with_lights(
                            room, media_player, message, volume, tts_settings
                        )
                        _LOGGER.warning("Room kWh alert: %s exceeded %d kWh", room_name, interval_hit)
                    except Exception as e:
                        _LOGGER.error("Failed to send room kWh alert: %s", e)

        # Check home kWh limit
        home_limit = pe.get("home_kwh_limit", 22)
        if await self.config_manager.async_should_send_home_kwh_alert(home_limit):
            # Find a media player to use
            media_player = None
            room_for_tts = None
            for room in rooms:
                if room.get("media_player"):
                    media_player = room["media_player"]
                    room_for_tts = room
                    break

            if media_player and room_for_tts:
                msg_template = tts_settings.get("home_kwh_warn_msg", "")
                if msg_template:
                    total_kwh = self.config_manager.get_total_day_kwh()
                    message = msg_template.format(
                        prefix=prefix,
                        kwh_limit=spoken_cardinal(home_limit),
                    )
                    try:
                        volume = float(room_for_tts.get("volume", 0.7))
                        await self._async_send_tts_with_lights(
                            room_for_tts, media_player, message, volume, tts_settings
                        )
                        _LOGGER.warning("Home kWh alert: exceeded %d kWh (current: %.1f)", home_limit, total_kwh)
                    except Exception as e:
                        _LOGGER.error("Failed to send home kWh alert: %s", e)

    async def _check_breaker_lines(self, tts_settings: dict) -> None:
        """Check breaker line loads and trigger warnings/shutoffs."""
        energy_config = self.config_manager.energy_config
        breaker_lines = energy_config.get("breaker_lines", [])
        
        for breaker in breaker_lines:
            breaker_id = breaker.get("id")
            breaker_name = breaker.get("name", "Breaker")
            max_load = breaker.get("max_load", 2400)
            threshold = breaker.get("threshold", 0)
            
            # Get all outlets on this breaker
            outlets = self.config_manager.get_outlets_for_breaker(breaker_id)
            
            # Calculate total power for this breaker
            breaker_total_watts = 0.0
            for outlet in outlets:
                if outlet.get("plug1_entity"):
                    breaker_total_watts += self._get_power_value(outlet["plug1_entity"])
                if outlet.get("plug2_entity"):
                    breaker_total_watts += self._get_power_value(outlet["plug2_entity"])
            
            # Get room for responsive lights (first room with outlets on this breaker and responsive lights)
            # Fallback: first room with media_player
            room_for_lights = self._get_room_for_breaker(breaker_id)
            media_player = None
            volume = tts_settings.get("volume", 0.7)
            if room_for_lights:
                media_player = room_for_lights.get("media_player")
                volume = float(room_for_lights.get("volume", 0.7))
            if not media_player:
                for room in energy_config.get("rooms", []):
                    if room.get("media_player"):
                        media_player = room["media_player"]
                        room_for_lights = room if room_for_lights is None else room_for_lights
                        break
            
            # Check warning threshold (near max)
            if threshold > 0 and breaker_total_watts >= threshold:
                # Check cooldown
                now = dt_util.now()
                last_warning = self._last_breaker_warnings.get(breaker_id)
                if not last_warning or (now - last_warning).total_seconds() >= ALERT_COOLDOWN:
                    self._last_breaker_warnings[breaker_id] = now
                    
                    prefix = tts_settings.get("prefix", DEFAULT_TTS_PREFIX)
                    msg_template = tts_settings.get("breaker_warn_msg", DEFAULT_BREAKER_WARN_MSG)
                    message = msg_template.format(
                        prefix=prefix,
                        breaker_name=breaker_name,
                        watts=int(breaker_total_watts),
                        max_load=max_load,
                    )
                    
                    if media_player:
                        if room_for_lights:
                            await self._async_send_tts_with_lights(
                                room_for_lights, media_player, message, volume, tts_settings
                            )
                        else:
                            await async_send_tts_or_queue(
                                self.hass,
                                media_player=media_player,
                                message=message,
                                language=tts_settings.get("language"),
                                volume=volume,
                            )
                    _LOGGER.warning("Breaker warning: %s - %dW", breaker_name, int(breaker_total_watts))
            
            # Check shutoff threshold (at max)
            if max_load > 0 and breaker_total_watts >= max_load:
                # Don't re-trigger if already in shutoff cycle
                if self._breaker_shutoff_pending.get(breaker_id):
                    continue
                
                # Check cooldown
                now = dt_util.now()
                last_shutoff = self._last_breaker_shutoffs.get(breaker_id)
                if last_shutoff and (now - last_shutoff).total_seconds() < ALERT_COOLDOWN:
                    continue
                
                self._breaker_shutoff_pending[breaker_id] = True
                self._last_breaker_shutoffs[breaker_id] = now
                
                try:
                    # Send TTS message (with optional responsive light loop)
                    prefix = tts_settings.get("prefix", DEFAULT_TTS_PREFIX)
                    msg_template = tts_settings.get("breaker_shutoff_msg", DEFAULT_BREAKER_SHUTOFF_MSG)
                    message = msg_template.format(
                        prefix=prefix,
                        breaker_name=breaker_name,
                        watts=spoken_cardinal(breaker_total_watts),
                        max_load=spoken_cardinal(max_load),
                    )
                    
                    if media_player:
                        if room_for_lights:
                            await self._async_send_tts_with_lights(
                                room_for_lights, media_player, message, volume, tts_settings
                            )
                        else:
                            await async_send_tts_or_queue(
                                self.hass,
                                media_player=media_player,
                                message=message,
                                language=tts_settings.get("language"),
                                volume=volume,
                            )
                    
                    # Turn off ALL switches for all outlets on this breaker
                    switch_entities = []
                    for outlet in outlets:
                        if outlet.get("plug1_switch") and outlet["plug1_switch"].startswith("switch."):
                            switch_entities.append(outlet["plug1_switch"])
                        if outlet.get("plug2_switch") and outlet["plug2_switch"].startswith("switch."):
                            switch_entities.append(outlet["plug2_switch"])
                    
                    if switch_entities:
                        # Turn off all switches
                        await self.hass.services.async_call(
                            "switch", "turn_off",
                            {"entity_id": switch_entities},
                            blocking=True,
                        )
                        _LOGGER.warning(
                            "Breaker shutoff triggered: %s - %dW, turned off %d switches",
                            breaker_name, int(breaker_total_watts), len(switch_entities)
                        )
                        
                        # Wait 5 seconds
                        await asyncio.sleep(SHUTOFF_RESET_DELAY)
                        
                        # Turn all switches back on
                        await self.hass.services.async_call(
                            "switch", "turn_on",
                            {"entity_id": switch_entities},
                            blocking=True,
                        )
                        _LOGGER.info(
                            "Breaker reset after shutoff: %s - %d switches turned back on",
                            breaker_name, len(switch_entities)
                        )
                except Exception as e:
                    _LOGGER.error("Breaker shutoff error: %s", e)
                finally:
                    self._breaker_shutoff_pending[breaker_id] = False

    def _get_stove_configs(self) -> list[tuple[str, dict, dict]]:
        """Get all configured stove devices with (room_id, stove_outlet, room)."""
        energy_config = self.config_manager.energy_config
        result = []
        for room in energy_config.get("rooms", []):
            room_id = room.get("id", room["name"].lower().replace(" ", "_"))
            for outlet in room.get("outlets", []):
                if outlet.get("type") == "stove":
                    result.append((room_id, outlet, room))
                    break
        return result

    def _get_microwave_stove_pairs(self) -> list[tuple[dict, dict, dict]]:
        """Get (microwave_outlet, stove_outlet, room) for rooms with both."""
        energy_config = self.config_manager.energy_config
        result = []
        for room in energy_config.get("rooms", []):
            outlets = room.get("outlets", [])
            stoves = [o for o in outlets if o.get("type") == "stove"]
            microwaves = [o for o in outlets if o.get("type") == "microwave"]
            if not stoves or not microwaves:
                continue
            stove = stoves[0]
            for mw in microwaves:
                if mw.get("plug1_entity") and stove.get("plug1_switch"):
                    result.append((mw, stove, room))
                    break
        return result

    async def _check_stove_safety(self, tts_settings: dict) -> None:
        """Check stove safety per device - monitor stove state, presence, microwave, and manage timers."""
        # Microwave safety first: cut stove when microwave on (shared breaker)
        # Requires both stove safety and microwave safety to be enabled
        for mw_outlet, stove_outlet, room in self._get_microwave_stove_pairs():
            if stove_outlet.get("stove_safety_enabled") is False:
                continue
            if mw_outlet.get("microwave_safety_enabled") is False:
                continue
            mw_entity = mw_outlet.get("plug1_entity")
            stove_switch = stove_outlet.get("plug1_switch")
            stove_entity = stove_outlet.get("plug1_entity")
            mw_threshold = int(mw_outlet.get("microwave_power_threshold", 50))
            media_player = room.get("media_player")
            volume = float(room.get("volume", 0.7))
            if not mw_entity or not stove_switch or not stove_entity:
                continue
            key = stove_entity
            self._stove_powered_off_by_microwave.setdefault(key, False)
            mw_power = self._get_power_value(mw_entity)
            stove_power = self._get_power_value(stove_entity)
            stove_threshold = int(stove_outlet.get("stove_power_threshold", 100))
            stove_is_on = stove_power > stove_threshold
            mw_is_on = mw_power > mw_threshold
            if mw_is_on and stove_is_on:
                if not self._stove_powered_off_by_microwave[key]:
                    self._stove_powered_off_by_microwave[key] = True
                    try:
                        await self.hass.services.async_call(
                            "switch", "turn_off",
                            {"entity_id": stove_switch},
                            blocking=True,
                        )
                        if media_player:
                            prefix = tts_settings.get("prefix", DEFAULT_TTS_PREFIX)
                            msg_template = tts_settings.get(
                                "microwave_cut_power_msg", DEFAULT_MICROWAVE_CUT_MSG
                            )
                            message = msg_template.format(prefix=prefix)
                            await self._async_send_tts_with_lights(
                                room, media_player, message, volume, tts_settings
                            )
                        _LOGGER.warning("Stove power cut: microwave is on (shared breaker)")
                    except Exception as e:
                        _LOGGER.error("Failed to cut stove for microwave: %s", e)
                        self._stove_powered_off_by_microwave[key] = False
            elif self._stove_powered_off_by_microwave[key] and not mw_is_on:
                try:
                    await self.hass.services.async_call(
                        "switch", "turn_on",
                        {"entity_id": stove_switch},
                        blocking=True,
                    )
                    if media_player:
                        prefix = tts_settings.get("prefix", DEFAULT_TTS_PREFIX)
                        msg_template = tts_settings.get(
                            "microwave_restore_power_msg", DEFAULT_MICROWAVE_RESTORE_MSG
                        )
                        message = msg_template.format(prefix=prefix)
                        await self._async_send_tts_with_lights(
                            room, media_player, message, volume, tts_settings
                        )
                    self._stove_powered_off_by_microwave[key] = False
                    self._stove_state[key] = "on"
                    _LOGGER.info("Stove power restored: microwave is off")
                except Exception as e:
                    _LOGGER.error("Failed to restore stove after microwave: %s", e)

        # Stove safety per stove device
        for _room_id, stove_outlet, room in self._get_stove_configs():
            stove_plug_entity = stove_outlet.get("plug1_entity")
            stove_plug_switch = stove_outlet.get("plug1_switch")
            presence_sensor = stove_outlet.get("presence_sensor")
            if not stove_plug_entity or not presence_sensor:
                continue
            key = stove_plug_entity
            self._stove_state.setdefault(key, "off")
            self._stove_timer_start.setdefault(key, None)
            self._stove_timer_phase.setdefault(key, "none")
            self._stove_last_presence.setdefault(key, None)
            self._stove_15min_warn_sent.setdefault(key, False)
            self._stove_30sec_warn_sent.setdefault(key, False)
            self._stove_powered_off_by_microwave.setdefault(key, False)
            self._stove_power_below_since.setdefault(key, None)
            self._stove_power_above_since.setdefault(key, None)
            self._stove_presence_window_start.setdefault(key, None)
            self._stove_progress_last_boundary.setdefault(key, 0)

            stove_power_threshold = int(stove_outlet.get("stove_power_threshold", 100))
            stove_off_debounce = int(stove_outlet.get("stove_off_debounce_seconds", 10))
            stove_on_debounce = int(stove_outlet.get("stove_on_debounce_seconds", 0))
            timer_start_window = int(stove_outlet.get("timer_start_window_seconds", 10))
            cooking_time_minutes = int(stove_outlet.get("cooking_time_minutes", 15))
            final_warning_seconds = int(stove_outlet.get("final_warning_seconds", 30))
            cooking_time_sec = max(1, cooking_time_minutes) * 60
            final_warning_sec = max(1, min(final_warning_seconds, 300))
            media_player = room.get("media_player")
            volume = float(room.get("volume", 0.7))

            current_power = self._get_power_value(stove_plug_entity)
            stove_is_on = current_power > stove_power_threshold
            if self._stove_powered_off_by_microwave[key]:
                continue

            presence_state = self.hass.states.get(presence_sensor)
            state_val = (presence_state.state or "").lower() if presence_state else ""
            presence_detected = state_val in ("detected", "on")
            now = dt_util.now()

            # Stove on/off with debounce (electric stoves fluctuate at medium heat)
            if stove_is_on:
                if self._stove_power_above_since[key] is None:
                    self._stove_power_above_since[key] = now
                self._stove_power_below_since[key] = None
                elapsed_above = (now - self._stove_power_above_since[key]).total_seconds()
                if self._stove_state[key] != "on" and elapsed_above >= stove_on_debounce:
                    self._stove_state[key] = "on"
                    self._stove_15min_warn_sent[key] = False
                    self._stove_30sec_warn_sent[key] = False
                    if media_player:
                        prefix = tts_settings.get("prefix", DEFAULT_TTS_PREFIX)
                        msg_template = tts_settings.get("stove_on_msg", DEFAULT_STOVE_ON_MSG)
                        await async_send_tts_or_queue(
                            self.hass, media_player=media_player, message=msg_template.format(prefix=prefix),
                            language=tts_settings.get("language"), volume=volume,
                        )
                    _LOGGER.info("Stove turned on")
            else:
                if self._stove_power_below_since[key] is None:
                    self._stove_power_below_since[key] = now
                self._stove_power_above_since[key] = None
                elapsed_below = (now - self._stove_power_below_since[key]).total_seconds()
                if self._stove_state[key] == "on" and elapsed_below >= stove_off_debounce:
                    self._stove_state[key] = "off"
                    self._stove_timer_start[key] = None
                    self._stove_timer_phase[key] = "none"
                    self._stove_presence_window_start[key] = None
                    self._stove_15min_warn_sent[key] = False
                    self._stove_30sec_warn_sent[key] = False
                    self._stove_progress_last_boundary[key] = 0
                    if not self._stove_powered_off_by_microwave[key] and media_player:
                        prefix = tts_settings.get("prefix", DEFAULT_TTS_PREFIX)
                        msg_template = tts_settings.get("stove_off_msg", DEFAULT_STOVE_OFF_MSG)
                        await async_send_tts_or_queue(
                            self.hass, media_player=media_player, message=msg_template.format(prefix=prefix),
                            language=tts_settings.get("language"), volume=volume,
                        )
                    _LOGGER.info("Stove turned off")

            if not stove_is_on:
                continue

            if presence_detected:
                self._stove_presence_window_start[key] = None
                if self._stove_timer_phase[key] != "none":
                    self._stove_timer_start[key] = None
                    self._stove_timer_phase[key] = "none"
                    self._stove_15min_warn_sent[key] = False
                    self._stove_30sec_warn_sent[key] = False
                    self._stove_progress_last_boundary[key] = 0
                    _LOGGER.info("Presence detected - timer reset")
                self._stove_last_presence[key] = "on"
            else:
                # Cooking timer: presence window before starting (don't start if person briefly left)
                window_start = self._stove_presence_window_start[key]
                if self._stove_last_presence[key] == "on":
                    if window_start is None:
                        self._stove_presence_window_start[key] = now
                    else:
                        window_elapsed = (now - window_start).total_seconds()
                        if window_elapsed >= timer_start_window:
                            self._stove_timer_start[key] = now
                            self._stove_timer_phase[key] = "15min"
                            self._stove_presence_window_start[key] = None
                            self._stove_15min_warn_sent[key] = False
                            self._stove_30sec_warn_sent[key] = False
                            if media_player:
                                prefix = tts_settings.get("prefix", DEFAULT_TTS_PREFIX)
                                msg_template = tts_settings.get(
                                    "stove_timer_started_msg", DEFAULT_STOVE_TIMER_STARTED_MSG
                                )
                                await async_send_tts_or_queue(
                                    self.hass, media_player=media_player,
                                    message=msg_template.format(
                                        prefix=prefix,
                                        cooking_time_minutes=spoken_cardinal(cooking_time_minutes),
                                        final_warning_seconds=spoken_cardinal(final_warning_sec),
                                    ),
                                    language=tts_settings.get("language"), volume=volume,
                                )
                            _LOGGER.info("Presence left - starting cooking timer (%d min)", cooking_time_minutes)
                            self._stove_last_presence[key] = "off"

                if self._stove_timer_start[key]:
                    now = dt_util.now()
                    elapsed = (now - self._stove_timer_start[key]).total_seconds()
                    if self._stove_timer_phase[key] == "15min":
                        cfg_iv = int(stove_outlet.get("stove_timer_tts_interval_seconds", 0) or 0)
                        interval_sec = cfg_iv if cfg_iv > 0 else max(60, cooking_time_sec // 4)
                        if (
                            media_player
                            and interval_sec > 0
                            and elapsed < cooking_time_sec - 0.5
                        ):
                            bnd = int(elapsed // interval_sec)
                            last_b = self._stove_progress_last_boundary.get(key, 0)
                            if bnd > last_b and bnd >= 1:
                                rem = max(0, int(cooking_time_sec - elapsed))
                                rm, rs = rem // 60, rem % 60
                                prefix = tts_settings.get("prefix", DEFAULT_TTS_PREFIX)
                                msg_tmpl = (
                                    tts_settings.get("stove_timer_progress_msg") or ""
                                ).strip() or DEFAULT_STOVE_TIMER_PROGRESS_MSG
                                room_name = room.get("name", "Kitchen")
                                try:
                                    message = msg_tmpl.format(
                                        prefix=prefix,
                                        room_name=room_name,
                                        minutes_remaining=spoken_cardinal(rm),
                                        seconds_remaining=spoken_cardinal(rs),
                                    )
                                    await self._async_send_tts_with_lights(
                                        room, media_player, message, volume, tts_settings
                                    )
                                except (KeyError, ValueError) as e:
                                    _LOGGER.warning("Stove timer progress TTS format failed: %s", e)
                                self._stove_progress_last_boundary[key] = bnd
                        if elapsed >= cooking_time_sec:
                            if not self._stove_15min_warn_sent[key]:
                                if media_player:
                                    prefix = tts_settings.get("prefix", DEFAULT_TTS_PREFIX)
                                    msg_template = tts_settings.get("stove_15min_warn_msg", DEFAULT_STOVE_15MIN_WARN_MSG)
                                    message = msg_template.format(
                                        prefix=prefix, cooking_time_minutes=cooking_time_minutes,
                                        final_warning_seconds=final_warning_sec,
                                    )
                                    await self._async_send_tts_with_lights(
                                        room, media_player, message, volume, tts_settings
                                    )
                                self._stove_15min_warn_sent[key] = True
                                _LOGGER.warning("Stove cooking-time warning - starting %ds countdown", final_warning_sec)
                            # When shutoff disabled, skip 30sec final warning (it's only relevant before shutoff)
                            if stove_outlet.get("stove_safety_enabled") is False:
                                self._stove_timer_start[key] = None
                                self._stove_timer_phase[key] = "none"
                                self._stove_15min_warn_sent[key] = False
                                self._stove_30sec_warn_sent[key] = False
                            else:
                                self._stove_timer_start[key] = now
                                self._stove_timer_phase[key] = "30sec"
                                self._stove_30sec_warn_sent[key] = False
                    elif self._stove_timer_phase[key] == "30sec":
                        if elapsed >= final_warning_sec:
                            if not self._stove_30sec_warn_sent[key]:
                                if media_player:
                                    prefix = tts_settings.get("prefix", DEFAULT_TTS_PREFIX)
                                    msg_template = tts_settings.get("stove_30sec_warn_msg", DEFAULT_STOVE_30SEC_WARN_MSG)
                                    await async_send_tts_or_queue(
                                        self.hass, media_player=media_player,
                                        message=msg_template.format(
                                            prefix=prefix,
                                            cooking_time_minutes=spoken_cardinal(cooking_time_minutes),
                                            final_warning_seconds=spoken_cardinal(final_warning_sec),
                                        ),
                                        language=tts_settings.get("language"), volume=volume,
                                    )
                                self._stove_30sec_warn_sent[key] = True
                            # Only turn off stove if stove_safety_enabled; when off, TTS still plays but no shutoff
                            if stove_outlet.get("stove_safety_enabled") is not False and stove_plug_switch:
                                try:
                                    await self.hass.services.async_call(
                                        "switch", "turn_off",
                                        {"entity_id": stove_plug_switch},
                                        blocking=True,
                                    )
                                    if media_player:
                                        prefix = tts_settings.get("prefix", DEFAULT_TTS_PREFIX)
                                        msg_template = tts_settings.get("stove_auto_off_msg", DEFAULT_STOVE_AUTO_OFF_MSG)
                                        message = msg_template.format(prefix=prefix)
                                        await self._async_send_tts_with_lights(
                                            room, media_player, message, volume, tts_settings
                                        )
                                    _LOGGER.warning("Stove automatically turned off for safety")
                                except Exception as e:
                                    _LOGGER.error("Failed to turn off stove: %s", e)
                            # Reset timer state in both cases (shutoff or TTS-only) to avoid re-triggering
                            self._stove_timer_start[key] = None
                            self._stove_timer_phase[key] = "none"
                            self._stove_15min_warn_sent[key] = False
                            self._stove_30sec_warn_sent[key] = False
                            self._stove_progress_last_boundary[key] = 0


async def async_start_energy_monitor(
    hass: HomeAssistant, config_manager: "ConfigManager"
) -> None:
    """Start the energy monitor."""
    monitor = EnergyMonitor(hass, config_manager)
    await monitor.async_start()
    hass.data[DOMAIN]["energy_monitor"] = monitor
    hass.data[DOMAIN]["energy_monitor_task"] = monitor._task
