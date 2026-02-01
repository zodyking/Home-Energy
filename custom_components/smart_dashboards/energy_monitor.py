"""Energy monitoring background task for Smart Dashboards."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import DOMAIN, ENERGY_CHECK_INTERVAL, ALERT_COOLDOWN
from .tts_helper import async_send_tts

if TYPE_CHECKING:
    from .config_manager import ConfigManager

_LOGGER = logging.getLogger(__name__)


class EnergyMonitor:
    """Monitor energy consumption and send TTS alerts."""

    def __init__(self, hass: HomeAssistant, config_manager: "ConfigManager") -> None:
        """Initialize the energy monitor."""
        self.hass = hass
        self.config_manager = config_manager
        self._running = False
        self._task: asyncio.Task | None = None
        self._last_alerts: dict[str, datetime] = {}
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
        """Check energy consumption for all rooms."""
        energy_config = self.config_manager.energy_config
        rooms = energy_config.get("rooms", [])
        tts_settings = energy_config.get("tts_settings", {})

        for room in rooms:
            room_id = room.get("id", room["name"].lower().replace(" ", "_"))
            room_name = room["name"]
            threshold = room.get("threshold", 0)
            media_player = room.get("media_player")

            if threshold <= 0:
                continue  # No threshold set

            # Calculate total room watts
            total_watts = 0.0
            for outlet in room.get("outlets", []):
                # Get plug 1 power
                if outlet.get("plug1_entity"):
                    watts = self._get_power_value(outlet["plug1_entity"])
                    total_watts += watts
                    # Track for day energy
                    await self.config_manager.async_add_energy_reading(
                        outlet["plug1_entity"], watts
                    )

                # Get plug 2 power
                if outlet.get("plug2_entity"):
                    watts = self._get_power_value(outlet["plug2_entity"])
                    total_watts += watts
                    # Track for day energy
                    await self.config_manager.async_add_energy_reading(
                        outlet["plug2_entity"], watts
                    )

            # Check if threshold exceeded
            if total_watts > threshold:
                await self._send_threshold_alert(
                    room_id=room_id,
                    room_name=room_name,
                    current_watts=total_watts,
                    threshold=threshold,
                    media_player=media_player,
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

    async def _send_threshold_alert(
        self,
        room_id: str,
        room_name: str,
        current_watts: float,
        threshold: int,
        media_player: str | None,
        tts_settings: dict,
    ) -> None:
        """Send TTS alert for threshold exceeded."""
        if not media_player:
            return

        # Check cooldown
        now = dt_util.now()
        last_alert = self._last_alerts.get(room_id)
        if last_alert and (now - last_alert).total_seconds() < ALERT_COOLDOWN:
            return  # Still in cooldown

        # Update last alert time
        self._last_alerts[room_id] = now

        # Format message
        message = (
            f"Warning: {room_name} power usage is {int(current_watts)} watts, "
            f"which exceeds the {threshold} watt threshold."
        )

        try:
            await async_send_tts(
                self.hass,
                media_player=media_player,
                message=message,
                language=tts_settings.get("language"),
                volume=tts_settings.get("volume"),
            )
            _LOGGER.warning(
                "Threshold alert sent for %s: %dW > %dW",
                room_name,
                int(current_watts),
                threshold,
            )
        except Exception as e:
            _LOGGER.error("Failed to send threshold alert: %s", e)


async def async_start_energy_monitor(
    hass: HomeAssistant, config_manager: "ConfigManager"
) -> None:
    """Start the energy monitor."""
    monitor = EnergyMonitor(hass, config_manager)
    await monitor.async_start()
    hass.data[DOMAIN]["energy_monitor"] = monitor
    hass.data[DOMAIN]["energy_monitor_task"] = monitor._task
