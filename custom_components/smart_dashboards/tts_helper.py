"""TTS helper functions for Smart Dashboards."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.const import ATTR_ENTITY_ID

from .const import DEFAULT_TTS_LANGUAGE, DEFAULT_TTS_VOLUME

_LOGGER = logging.getLogger(__name__)


async def async_send_tts(
    hass: HomeAssistant,
    media_player: str,
    message: str,
    language: str | None = None,
    volume: float | None = None,
    restore_volume: bool = True,
) -> None:
    """Send TTS message to a media player.

    Args:
        hass: Home Assistant instance
        media_player: Entity ID of the media player
        message: Text to speak
        language: TTS language (default: en)
        volume: Volume level 0-1 (optional, will set before TTS)
        restore_volume: Whether to restore original volume after TTS
    """
    if not message or not message.strip():
        _LOGGER.warning("Empty TTS message, skipping")
        return

    if not media_player:
        _LOGGER.warning("No media player specified for TTS")
        return

    # Check if media player exists
    state = hass.states.get(media_player)
    if state is None:
        _LOGGER.error("Media player %s not found", media_player)
        return

    original_volume = None

    # Set volume if specified
    if volume is not None:
        original_volume = state.attributes.get("volume_level")
        await async_set_volume(hass, media_player, volume)

    # Send TTS
    try:
        tts_data: dict[str, Any] = {
            ATTR_ENTITY_ID: media_player,
            "message": message.strip(),
        }

        if language:
            tts_data["language"] = language
        else:
            tts_data["language"] = DEFAULT_TTS_LANGUAGE

        # Use tts.speak service
        await hass.services.async_call(
            "tts",
            "speak",
            {
                ATTR_ENTITY_ID: media_player,
                "media_player_entity_id": media_player,
                "message": message.strip(),
                "language": language or DEFAULT_TTS_LANGUAGE,
            },
            blocking=True,
        )

        _LOGGER.debug("TTS sent to %s: %s", media_player, message[:50])

    except Exception as e:
        _LOGGER.error("Failed to send TTS: %s", e)
        # Try alternative TTS method (google_translate_say or cloud_say)
        try:
            await hass.services.async_call(
                "tts",
                "google_translate_say",
                {
                    ATTR_ENTITY_ID: media_player,
                    "message": message.strip(),
                    "language": language or DEFAULT_TTS_LANGUAGE,
                },
                blocking=True,
            )
        except Exception as e2:
            _LOGGER.error("Fallback TTS also failed: %s", e2)
            raise


async def async_set_volume(
    hass: HomeAssistant,
    media_player: str,
    volume: float,
) -> None:
    """Set volume on a media player.

    Args:
        hass: Home Assistant instance
        media_player: Entity ID of the media player
        volume: Volume level 0-1
    """
    if not media_player:
        return

    # Clamp volume to valid range
    volume = max(0.0, min(1.0, volume))

    try:
        await hass.services.async_call(
            "media_player",
            "volume_set",
            {
                ATTR_ENTITY_ID: media_player,
                "volume_level": volume,
            },
            blocking=True,
        )
        _LOGGER.debug("Volume set to %.2f on %s", volume, media_player)
    except Exception as e:
        _LOGGER.error("Failed to set volume on %s: %s", media_player, e)
        raise


async def async_get_volume(
    hass: HomeAssistant,
    media_player: str,
) -> float | None:
    """Get current volume of a media player.

    Args:
        hass: Home Assistant instance
        media_player: Entity ID of the media player

    Returns:
        Volume level 0-1 or None if unavailable
    """
    if not media_player:
        return None

    state = hass.states.get(media_player)
    if state is None:
        return None

    return state.attributes.get("volume_level")
