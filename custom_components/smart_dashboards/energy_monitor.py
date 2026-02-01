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
    DEFAULT_TTS_PREFIX,
    DEFAULT_ROOM_WARN_MSG,
    DEFAULT_OUTLET_WARN_MSG,
    DEFAULT_SHUTOFF_MSG,
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
        self._shutoff_pending: dict[str, bool] = {}  # Track plugs in shutoff cycle
        self._save_counter = 0

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
                await self._send_room_alert(
                    room_id=room_id,
                    room_name=room_name,
                    current_watts=room_total_watts,
                    media_player=media_player,
                    volume=room_volume,
                    tts_settings=tts_settings,
                )

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


async def async_start_energy_monitor(
    hass: HomeAssistant, config_manager: "ConfigManager"
) -> None:
    """Start the energy monitor."""
    monitor = EnergyMonitor(hass, config_manager)
    await monitor.async_start()
    hass.data[DOMAIN]["energy_monitor"] = monitor
    hass.data[DOMAIN]["energy_monitor_task"] = monitor._task
