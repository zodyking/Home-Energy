"""Energy monitoring background task for Smart Dashboards."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    ENERGY_CHECK_INTERVAL,
    ALERT_COOLDOWN,
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
    DEFAULT_STOVE_AUTO_OFF_MSG,
    DEFAULT_MICROWAVE_CUT_MSG,
    DEFAULT_MICROWAVE_RESTORE_MSG,
)
from .tts_helper import async_send_tts

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
        self._power_listener_unsub: list = []  # Unsubscribe callbacks for state listeners

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
        self._task = asyncio.create_task(self._monitor_loop())

        # Real-time energy: listen for state changes on power entities
        entity_ids = self._get_power_entity_ids()
        if entity_ids:
            # Seed initial state so we don't lose energy from startup to first update
            now = dt_util.utcnow()
            for eid in entity_ids:
                watts = self._get_power_value(eid)
                self.config_manager._last_power_update[eid] = {"watts": watts, "time": now}

            @callback
            def _on_power_state_change(event):
                new_state = event.data.get("new_state")
                if not new_state or new_state.state in ("unknown", "unavailable", ""):
                    return
                try:
                    watts = float(new_state.state)
                except (ValueError, TypeError):
                    return
                entity_id = event.data.get("entity_id", "")
                self.hass.async_create_task(
                    self.config_manager.async_add_energy_reading_on_state_change(
                        entity_id, watts
                    )
                )

            unsub = async_track_state_change_event(
                self.hass, entity_ids, _on_power_state_change
            )
            self._power_listener_unsub.append(unsub)

        _LOGGER.info("Energy monitor started (real-time accumulation for %d entities)", len(entity_ids))

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
        energy_config = self.config_manager.energy_config
        rooms = energy_config.get("rooms", [])
        tts_settings = energy_config.get("tts_settings", {})

        for room in rooms:
            room_id = room.get("id", room["name"].lower().replace(" ", "_"))
            room_name = room["name"]
            room_threshold = room.get("threshold", 0)
            media_player = room.get("media_player")
            room_volume = room.get("volume", tts_settings.get("volume", 0.7))

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
                                tracking_key = f"light_{room_id}_{outlet.get('name', 'light').lower().replace(' ', '_')}"
                                await self.config_manager.async_add_energy_reading(
                                    tracking_key, outlet_total_watts
                                )
                                # Record for intraday 24-hour charts
                                self.config_manager.record_intraday_power(tracking_key, outlet_total_watts)
                    room_total_watts += outlet_total_watts
                    continue

                # Get plug 1 power (state-change listener handles daily energy accumulation)
                plug1_watts = 0.0
                if outlet.get("plug1_entity"):
                    plug1_watts = self._get_power_value(outlet["plug1_entity"])
                    outlet_total_watts += plug1_watts
                    # Record for intraday 24-hour charts
                    self.config_manager.record_intraday_power(outlet["plug1_entity"], plug1_watts)

                    # Check plug 1 shutoff threshold
                    plug1_shutoff = outlet.get("plug1_shutoff", 0)
                    plug1_switch = outlet.get("plug1_switch")
                    if plug1_shutoff > 0 and plug1_watts > plug1_shutoff and plug1_switch:
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
                        )

                # Get plug 2 power (state-change listener handles daily energy accumulation)
                plug2_watts = 0.0
                if outlet.get("plug2_entity"):
                    plug2_watts = self._get_power_value(outlet["plug2_entity"])
                    outlet_total_watts += plug2_watts
                    # Record for intraday 24-hour charts
                    self.config_manager.record_intraday_power(outlet["plug2_entity"], plug2_watts)

                    # Check plug 2 shutoff threshold
                    plug2_shutoff = outlet.get("plug2_shutoff", 0)
                    plug2_switch = outlet.get("plug2_switch")
                    if plug2_shutoff > 0 and plug2_watts > plug2_shutoff and plug2_switch:
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
                        )

                room_total_watts += outlet_total_watts

                # Check outlet warning threshold (combined plugs)
                if outlet_threshold > 0 and outlet_total_watts > outlet_threshold:
                    await self._send_outlet_alert(
                        room_id=room_id,
                        room_name=room_name,
                        room=room,
                        outlet_name=outlet_name,
                        current_watts=outlet_total_watts,
                        media_player=media_player,
                        volume=room_volume,
                        tts_settings=tts_settings,
                    )

            # Check room threshold
            if room_threshold > 0 and room_total_watts > room_threshold:
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

        # Periodically save energy tracking data (every 60 seconds)
        self._save_counter += 1
        if self._save_counter >= 60:
            self._save_counter = 0
            await self.config_manager._async_save_energy_tracking()

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
                await self._async_send_tts_with_lights(
                    room, media_player, message, volume, tts_settings
                )
                # Count only when TTS was actually sent
                await self.config_manager.async_increment_shutoff(room_id)
            
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
    ) -> None:
        """Send TTS and optionally run responsive light loop if enabled for room."""
        if not media_player:
            return
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
        """Send TTS alert for room threshold exceeded."""
        if not media_player:
            return

        # Check cooldown
        now = dt_util.now()
        last_alert = self._last_room_alerts.get(room_id)
        if last_alert and (now - last_alert).total_seconds() < ALERT_COOLDOWN:
            return  # Still in cooldown

        # Update last alert time
        self._last_room_alerts[room_id] = now

        # Format message with prefix
        prefix = tts_settings.get("prefix", DEFAULT_TTS_PREFIX)
        msg_template = tts_settings.get("room_warn_msg", DEFAULT_ROOM_WARN_MSG)
        message = msg_template.format(
            prefix=prefix,
            room_name=room_name,
            watts=int(current_watts),
        )

        try:
            await self._async_send_tts_with_lights(
                room, media_player, message, volume, tts_settings
            )
            # Count only when TTS was actually sent
            await self.config_manager.async_increment_warning(room_id)
            _LOGGER.warning(
                "Room threshold alert: %s - %dW",
                room_name,
                int(current_watts),
            )
        except Exception as e:
            _LOGGER.error("Failed to send room threshold alert: %s", e)

    async def _send_outlet_alert(
        self,
        room_id: str,
        room_name: str,
        room: dict,
        outlet_name: str,
        current_watts: float,
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

        # Format message with prefix
        prefix = tts_settings.get("prefix", DEFAULT_TTS_PREFIX)
        msg_template = tts_settings.get("outlet_warn_msg", DEFAULT_OUTLET_WARN_MSG)
        message = msg_template.format(
            prefix=prefix,
            room_name=room_name,
            outlet_name=outlet_name,
            watts=int(current_watts),
        )

        try:
            await self._async_send_tts_with_lights(
                room, media_player, message, volume, tts_settings
            )
            # Count only when TTS was actually sent
            await self.config_manager.async_increment_warning(room_id)
            _LOGGER.warning(
                "Outlet threshold alert: %s %s - %dW",
                room_name,
                outlet_name,
                int(current_watts),
            )
        except Exception as e:
            _LOGGER.error("Failed to send outlet threshold alert: %s", e)

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
                    )
                    
                    if media_player:
                        if room_for_lights:
                            await self._async_send_tts_with_lights(
                                room_for_lights, media_player, message, volume, tts_settings
                            )
                        else:
                            await async_send_tts(
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
                    )
                    
                    if media_player:
                        if room_for_lights:
                            await self._async_send_tts_with_lights(
                                room_for_lights, media_player, message, volume, tts_settings
                            )
                        else:
                            await async_send_tts(
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

            stove_power_threshold = int(stove_outlet.get("stove_power_threshold", 100))
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

            if stove_is_on and self._stove_state[key] != "on":
                self._stove_state[key] = "on"
                self._stove_15min_warn_sent[key] = False
                self._stove_30sec_warn_sent[key] = False
                if media_player:
                    prefix = tts_settings.get("prefix", DEFAULT_TTS_PREFIX)
                    msg_template = tts_settings.get("stove_on_msg", DEFAULT_STOVE_ON_MSG)
                    await async_send_tts(
                        self.hass, media_player=media_player, message=msg_template.format(prefix=prefix),
                        language=tts_settings.get("language"), volume=volume,
                    )
                _LOGGER.info("Stove turned on")
            elif not stove_is_on and self._stove_state[key] == "on":
                self._stove_state[key] = "off"
                self._stove_timer_start[key] = None
                self._stove_timer_phase[key] = "none"
                self._stove_15min_warn_sent[key] = False
                self._stove_30sec_warn_sent[key] = False
                if not self._stove_powered_off_by_microwave[key] and media_player:
                    prefix = tts_settings.get("prefix", DEFAULT_TTS_PREFIX)
                    msg_template = tts_settings.get("stove_off_msg", DEFAULT_STOVE_OFF_MSG)
                    await async_send_tts(
                        self.hass, media_player=media_player, message=msg_template.format(prefix=prefix),
                        language=tts_settings.get("language"), volume=volume,
                    )
                _LOGGER.info("Stove turned off")

            if not stove_is_on:
                continue

            if presence_detected:
                if self._stove_timer_phase[key] != "none":
                    self._stove_timer_start[key] = None
                    self._stove_timer_phase[key] = "none"
                    self._stove_15min_warn_sent[key] = False
                    self._stove_30sec_warn_sent[key] = False
                    _LOGGER.info("Presence detected - timer reset")
                self._stove_last_presence[key] = "on"
            else:
                if self._stove_last_presence[key] == "on":
                    self._stove_timer_start[key] = dt_util.now()
                    self._stove_timer_phase[key] = "15min"
                    self._stove_15min_warn_sent[key] = False
                    self._stove_30sec_warn_sent[key] = False
                    if media_player:
                        prefix = tts_settings.get("prefix", DEFAULT_TTS_PREFIX)
                        msg_template = tts_settings.get(
                            "stove_timer_started_msg", DEFAULT_STOVE_TIMER_STARTED_MSG
                        )
                        await async_send_tts(
                            self.hass, media_player=media_player,
                            message=msg_template.format(
                                prefix=prefix, cooking_time_minutes=cooking_time_minutes,
                                final_warning_seconds=final_warning_sec,
                            ),
                            language=tts_settings.get("language"), volume=volume,
                        )
                    _LOGGER.info("Presence left - starting cooking timer (%d min)", cooking_time_minutes)
                self._stove_last_presence[key] = "off"

                if self._stove_timer_start[key]:
                    now = dt_util.now()
                    elapsed = (now - self._stove_timer_start[key]).total_seconds()
                    if self._stove_timer_phase[key] == "15min":
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
                                    await async_send_tts(
                                        self.hass, media_player=media_player,
                                        message=msg_template.format(
                                            prefix=prefix, cooking_time_minutes=cooking_time_minutes,
                                            final_warning_seconds=final_warning_sec,
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


async def async_start_energy_monitor(
    hass: HomeAssistant, config_manager: "ConfigManager"
) -> None:
    """Start the energy monitor."""
    monitor = EnergyMonitor(hass, config_manager)
    await monitor.async_start()
    hass.data[DOMAIN]["energy_monitor"] = monitor
    hass.data[DOMAIN]["energy_monitor_task"] = monitor._task
