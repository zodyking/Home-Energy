"""Energy monitoring background task for Smart Dashboards."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import DOMAIN, ENERGY_CHECK_INTERVAL, ALERT_COOLDOWN
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

                # Get plug 1 power
                if outlet.get("plug1_entity"):
                    watts = self._get_power_value(outlet["plug1_entity"])
                    outlet_total_watts += watts
                    # Track for day energy
                    await self.config_manager.async_add_energy_reading(
                        outlet["plug1_entity"], watts
                    )

                # Get plug 2 power
                if outlet.get("plug2_entity"):
                    watts = self._get_power_value(outlet["plug2_entity"])
                    outlet_total_watts += watts
                    # Track for day energy
                    await self.config_manager.async_add_energy_reading(
                        outlet["plug2_entity"], watts
                    )

                room_total_watts += outlet_total_watts

                # Check outlet threshold
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

        # Format message: "(Room Name) is pulling (room electricity total) watts"
        message = f"{room_name} is pulling {int(current_watts)} watts"

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

        # Format message: "(Room Name) (Outlet Name) is pulling (Outlet total) watts"
        message = f"{room_name} {outlet_name} is pulling {int(current_watts)} watts"

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
