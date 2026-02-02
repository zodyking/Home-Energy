"""Energy monitoring background task for Smart Dashboards."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant
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
        
        # Stove safety state
        self._stove_state = "off"  # "on" or "off"
        self._stove_timer_start: datetime | None = None
        self._stove_timer_phase = "none"  # "none", "15min", "30sec"
        self._stove_last_presence: str | None = None
        self._stove_15min_warn_sent = False
        self._stove_30sec_warn_sent = False
        self._stove_powered_off_by_microwave = False

    async def async_start(self) -> None:
        """Start the energy monitoring loop."""
        if self._running:
            return

        self._running = True
        self._task = asyncio.create_task(self._monitor_loop())
        _LOGGER.info("Energy monitor started")

    async def async_stop(self) -> None:
        """Stop the energy monitoring loop."""
        self._running = False
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

                # Get plug 1 power and check shutoff threshold
                plug1_watts = 0.0
                if outlet.get("plug1_entity"):
                    plug1_watts = self._get_power_value(outlet["plug1_entity"])
                    outlet_total_watts += plug1_watts
                    await self.config_manager.async_add_energy_reading(
                        outlet["plug1_entity"], plug1_watts
                    )
                    
                    # Check plug 1 shutoff threshold
                    plug1_shutoff = outlet.get("plug1_shutoff", 0)
                    plug1_switch = outlet.get("plug1_switch")
                    if plug1_shutoff > 0 and plug1_watts > plug1_shutoff and plug1_switch:
                        await self._handle_plug_shutoff(
                            room_id=room_id,
                            room_name=room_name,
                            outlet_name=outlet_name,
                            plug_name="Plug 1",
                            switch_entity=plug1_switch,
                            media_player=media_player,
                            volume=room_volume,
                            tts_settings=tts_settings,
                        )

                # Get plug 2 power and check shutoff threshold
                plug2_watts = 0.0
                if outlet.get("plug2_entity"):
                    plug2_watts = self._get_power_value(outlet["plug2_entity"])
                    outlet_total_watts += plug2_watts
                    await self.config_manager.async_add_energy_reading(
                        outlet["plug2_entity"], plug2_watts
                    )
                    
                    # Check plug 2 shutoff threshold
                    plug2_shutoff = outlet.get("plug2_shutoff", 0)
                    plug2_switch = outlet.get("plug2_switch")
                    if plug2_shutoff > 0 and plug2_watts > plug2_shutoff and plug2_switch:
                        await self._handle_plug_shutoff(
                            room_id=room_id,
                            room_name=room_name,
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
                    await self.config_manager.async_increment_warning(room_id)
                    await self._send_outlet_alert(
                        room_id=room_id,
                        room_name=room_name,
                        outlet_name=outlet_name,
                        current_watts=outlet_total_watts,
                        media_player=media_player,
                        volume=room_volume,
                        tts_settings=tts_settings,
                    )

            # Check room threshold
            if room_threshold > 0 and room_total_watts > room_threshold:
                await self.config_manager.async_increment_warning(room_id)
                await self._send_room_alert(
                    room_id=room_id,
                    room_name=room_name,
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
            # Increment shutoff count
            await self.config_manager.async_increment_shutoff(room_id)
            
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
            
            # Send TTS message
            if media_player:
                prefix = tts_settings.get("prefix", DEFAULT_TTS_PREFIX)
                msg_template = tts_settings.get("shutoff_msg", DEFAULT_SHUTOFF_MSG)
                message = msg_template.format(
                    prefix=prefix,
                    room_name=room_name,
                    outlet_name=outlet_name,
                    plug=plug_name,
                )
                
                await async_send_tts(
                    self.hass,
                    media_player=media_player,
                    message=message,
                    language=tts_settings.get("language"),
                    volume=volume,
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

    async def _send_room_alert(
        self,
        room_id: str,
        room_name: str,
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
            await async_send_tts(
                self.hass,
                media_player=media_player,
                message=message,
                language=tts_settings.get("language"),
                volume=volume,
            )
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
            await async_send_tts(
                self.hass,
                media_player=media_player,
                message=message,
                language=tts_settings.get("language"),
                volume=volume,
            )
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
            
            # Check if we need a media player (use first room's media player or find one)
            media_player = None
            for room in energy_config.get("rooms", []):
                if room.get("media_player"):
                    media_player = room["media_player"]
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
                        await async_send_tts(
                            self.hass,
                            media_player=media_player,
                            message=message,
                            language=tts_settings.get("language"),
                            volume=tts_settings.get("volume", 0.7),
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
                    # Send TTS message
                    prefix = tts_settings.get("prefix", DEFAULT_TTS_PREFIX)
                    msg_template = tts_settings.get("breaker_shutoff_msg", DEFAULT_BREAKER_SHUTOFF_MSG)
                    message = msg_template.format(
                        prefix=prefix,
                        breaker_name=breaker_name,
                    )
                    
                    if media_player:
                        await async_send_tts(
                            self.hass,
                            media_player=media_player,
                            message=message,
                            language=tts_settings.get("language"),
                            volume=tts_settings.get("volume", 0.7),
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

    async def _check_stove_safety(self, tts_settings: dict) -> None:
        """Check stove safety - monitor stove state, presence, microwave, and manage timers."""
        energy_config = self.config_manager.energy_config
        stove_config = energy_config.get("stove_safety", {})
        
        stove_plug_entity = stove_config.get("stove_plug_entity")
        stove_plug_switch = stove_config.get("stove_plug_switch")
        stove_power_threshold = stove_config.get("stove_power_threshold", 100)
        cooking_time_minutes = int(stove_config.get("cooking_time_minutes", 15))
        final_warning_seconds = int(stove_config.get("final_warning_seconds", 30))
        cooking_time_sec = max(1, cooking_time_minutes) * 60
        final_warning_sec = max(1, min(final_warning_seconds, 300))
        presence_sensor = stove_config.get("presence_sensor")
        media_player = stove_config.get("media_player")
        volume = stove_config.get("volume", 0.7)
        microwave_plug_entity = stove_config.get("microwave_plug_entity")
        microwave_threshold = int(stove_config.get("microwave_power_threshold", 50))
        
        # Skip if not configured
        if not stove_plug_entity or not presence_sensor:
            return
        
        # Get current stove power
        current_power = self._get_power_value(stove_plug_entity)
        stove_is_on = current_power > stove_power_threshold
        
        # Microwave safety: if microwave and stove share a breaker, cut stove when microwave is on
        if microwave_plug_entity and stove_plug_switch and microwave_threshold >= 0:
            microwave_power = self._get_power_value(microwave_plug_entity)
            microwave_is_on = microwave_power > microwave_threshold
            
            if microwave_is_on and stove_is_on:
                # Cut power to stove, play TTS
                if not self._stove_powered_off_by_microwave:
                    self._stove_powered_off_by_microwave = True
                    try:
                        await self.hass.services.async_call(
                            "switch", "turn_off",
                            {"entity_id": stove_plug_switch},
                            blocking=True,
                        )
                        if media_player:
                            prefix = tts_settings.get("prefix", DEFAULT_TTS_PREFIX)
                            msg_template = tts_settings.get(
                                "microwave_cut_power_msg", DEFAULT_MICROWAVE_CUT_MSG
                            )
                            message = msg_template.format(prefix=prefix)
                            await async_send_tts(
                                self.hass,
                                media_player=media_player,
                                message=message,
                                language=tts_settings.get("language"),
                                volume=volume,
                            )
                        _LOGGER.warning("Stove power cut: microwave is on (shared breaker)")
                    except Exception as e:
                        _LOGGER.error("Failed to cut stove for microwave: %s", e)
                        self._stove_powered_off_by_microwave = False
                return  # Stove is now off; skip presence/timer logic this cycle
            
            if self._stove_powered_off_by_microwave and not microwave_is_on:
                # Microwave off - restore stove power, play TTS
                try:
                    await self.hass.services.async_call(
                        "switch", "turn_on",
                        {"entity_id": stove_plug_switch},
                        blocking=True,
                    )
                    if media_player:
                        prefix = tts_settings.get("prefix", DEFAULT_TTS_PREFIX)
                        msg_template = tts_settings.get(
                            "microwave_restore_power_msg", DEFAULT_MICROWAVE_RESTORE_MSG
                        )
                        message = msg_template.format(prefix=prefix)
                        await async_send_tts(
                            self.hass,
                            media_player=media_player,
                            message=message,
                            language=tts_settings.get("language"),
                            volume=volume,
                        )
                    self._stove_powered_off_by_microwave = False
                    self._stove_state = "on"  # So we don't re-announce "stove on"
                    _LOGGER.info("Stove power restored: microwave is off")
                except Exception as e:
                    _LOGGER.error("Failed to restore stove after microwave: %s", e)
                return
        
        # Get current presence state
        # Present: detected, on | Not present: clear, cleared, unavailable, unknown, off
        presence_state = self.hass.states.get(presence_sensor)
        state_val = (presence_state.state or "").lower() if presence_state else ""
        presence_detected = state_val in ("detected", "on")
        
        # Detect stove state changes
        if stove_is_on and self._stove_state != "on":
            # Stove just turned on
            self._stove_state = "on"
            self._stove_15min_warn_sent = False
            self._stove_30sec_warn_sent = False
            
            if media_player:
                prefix = tts_settings.get("prefix", DEFAULT_TTS_PREFIX)
                msg_template = tts_settings.get("stove_on_msg", DEFAULT_STOVE_ON_MSG)
                message = msg_template.format(prefix=prefix)
                await async_send_tts(
                    self.hass,
                    media_player=media_player,
                    message=message,
                    language=tts_settings.get("language"),
                    volume=volume,
                )
            _LOGGER.info("Stove turned on")
        
        elif not stove_is_on and self._stove_state == "on":
            # Stove just turned off (do not announce if we cut it for microwave)
            self._stove_state = "off"
            self._stove_timer_start = None
            self._stove_timer_phase = "none"
            self._stove_15min_warn_sent = False
            self._stove_30sec_warn_sent = False
            
            if not self._stove_powered_off_by_microwave and media_player:
                prefix = tts_settings.get("prefix", DEFAULT_TTS_PREFIX)
                msg_template = tts_settings.get("stove_off_msg", DEFAULT_STOVE_OFF_MSG)
                message = msg_template.format(prefix=prefix)
                await async_send_tts(
                    self.hass,
                    media_player=media_player,
                    message=message,
                    language=tts_settings.get("language"),
                    volume=volume,
                )
            _LOGGER.info("Stove turned off")
        
        # Only process timers if stove is on
        if not stove_is_on:
            return
        
        # Check presence state changes
        if presence_detected:
            # Presence detected - stop/reset timer
            if self._stove_timer_phase != "none":
                self._stove_timer_start = None
                self._stove_timer_phase = "none"
                self._stove_15min_warn_sent = False
                self._stove_30sec_warn_sent = False
                _LOGGER.info("Presence detected - timer reset")
            
            self._stove_last_presence = "on"
        
        elif not presence_detected:
            # No presence - manage timer
            if self._stove_last_presence == "on":
                # Just left - start cooking timer and announce
                self._stove_timer_start = dt_util.now()
                self._stove_timer_phase = "15min"
                self._stove_15min_warn_sent = False
                self._stove_30sec_warn_sent = False
                if media_player:
                    prefix = tts_settings.get("prefix", DEFAULT_TTS_PREFIX)
                    msg_template = tts_settings.get(
                        "stove_timer_started_msg", DEFAULT_STOVE_TIMER_STARTED_MSG
                    )
                    message = msg_template.format(
                        prefix=prefix,
                        cooking_time_minutes=cooking_time_minutes,
                        final_warning_seconds=final_warning_sec,
                    )
                    await async_send_tts(
                        self.hass,
                        media_player=media_player,
                        message=message,
                        language=tts_settings.get("language"),
                        volume=volume,
                    )
                _LOGGER.info("Presence left - starting cooking timer (%d min)", cooking_time_minutes)
            
            self._stove_last_presence = "off"
            
            # Process timer if running
            if self._stove_timer_start:
                now = dt_util.now()
                elapsed = (now - self._stove_timer_start).total_seconds()
                
                if self._stove_timer_phase == "15min":
                    if elapsed >= cooking_time_sec:
                        # Cooking time expired - send warning and start final countdown
                        if not self._stove_15min_warn_sent:
                            if media_player:
                                prefix = tts_settings.get("prefix", DEFAULT_TTS_PREFIX)
                                msg_template = tts_settings.get("stove_15min_warn_msg", DEFAULT_STOVE_15MIN_WARN_MSG)
                                message = msg_template.format(
                                    prefix=prefix,
                                    cooking_time_minutes=cooking_time_minutes,
                                    final_warning_seconds=final_warning_sec,
                                )
                                await async_send_tts(
                                    self.hass,
                                    media_player=media_player,
                                    message=message,
                                    language=tts_settings.get("language"),
                                    volume=volume,
                                )
                            self._stove_15min_warn_sent = True
                            _LOGGER.warning("Stove cooking-time warning - starting %ds countdown", final_warning_sec)
                        
                        # Start final warning countdown
                        self._stove_timer_start = now
                        self._stove_timer_phase = "30sec"
                        self._stove_30sec_warn_sent = False
                
                elif self._stove_timer_phase == "30sec":
                    if elapsed >= final_warning_sec:
                        # Final warning expired - turn off stove
                        if not self._stove_30sec_warn_sent:
                            # Send final warning
                            if media_player:
                                prefix = tts_settings.get("prefix", DEFAULT_TTS_PREFIX)
                                msg_template = tts_settings.get("stove_30sec_warn_msg", DEFAULT_STOVE_30SEC_WARN_MSG)
                                message = msg_template.format(
                                    prefix=prefix,
                                    cooking_time_minutes=cooking_time_minutes,
                                    final_warning_seconds=final_warning_sec,
                                )
                                await async_send_tts(
                                    self.hass,
                                    media_player=media_player,
                                    message=message,
                                    language=tts_settings.get("language"),
                                    volume=volume,
                                )
                            self._stove_30sec_warn_sent = True
                        
                        # Turn off stove switch
                        if stove_plug_switch:
                            try:
                                await self.hass.services.async_call(
                                    "switch", "turn_off",
                                    {"entity_id": stove_plug_switch},
                                    blocking=True,
                                )
                                
                                # Send shutoff TTS
                                if media_player:
                                    prefix = tts_settings.get("prefix", DEFAULT_TTS_PREFIX)
                                    msg_template = tts_settings.get("stove_auto_off_msg", DEFAULT_STOVE_AUTO_OFF_MSG)
                                    message = msg_template.format(prefix=prefix)
                                    await async_send_tts(
                                        self.hass,
                                        media_player=media_player,
                                        message=message,
                                        language=tts_settings.get("language"),
                                        volume=volume,
                                    )
                                
                                # Reset timer state
                                self._stove_timer_start = None
                                self._stove_timer_phase = "none"
                                self._stove_15min_warn_sent = False
                                self._stove_30sec_warn_sent = False
                                
                                _LOGGER.warning("Stove automatically turned off for safety")
                            except Exception as e:
                                _LOGGER.error("Failed to turn off stove: %s", e)


async def async_start_energy_monitor(
    hass: HomeAssistant, config_manager: "ConfigManager"
) -> None:
    """Start the energy monitor."""
    monitor = EnergyMonitor(hass, config_manager)
    await monitor.async_start()
    hass.data[DOMAIN]["energy_monitor"] = monitor
    hass.data[DOMAIN]["energy_monitor_task"] = monitor._task
