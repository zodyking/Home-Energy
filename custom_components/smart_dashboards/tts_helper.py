"""TTS helper functions for Smart Dashboards."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.const import ATTR_ENTITY_ID

from .const import DEFAULT_TTS_LANGUAGE, DEFAULT_TTS_VOLUME

_LOGGER = logging.getLogger(__name__)

# States in which TTS may be sent; do not send when off, playing, paused, etc.
READY_FOR_TTS_STATES = ("on", "idle", "standby")


def is_media_player_ready_for_tts(hass: HomeAssistant, media_player: str) -> bool:
    """Return True if media player is ready for TTS (on, idle, or standby only)."""
    state = hass.states.get(media_player)
    if state is None:
        return False
    return (state.state or "").lower() in READY_FOR_TTS_STATES


async def async_send_tts(
    hass: HomeAssistant,
    media_player: str,
    message: str,
    language: str | None = None,
    volume: float | None = None,
    tts_entity: str | None = None,
    blocking: bool = False,
) -> None:
    """Send TTS message to a media player.

    Args:
        hass: Home Assistant instance
        media_player: Entity ID of the media player
        message: Text to speak
        language: TTS language (default: en)
        volume: Volume level 0-1 (optional, will set before TTS)
        tts_entity: TTS engine entity (e.g., tts.google_translate_en_com)
        blocking: If True, wait for TTS to complete. Default False to avoid blocking
            the energy monitor when decoder issues occur (e.g. Apple TV/HomePod).
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

    # Set volume if specified
    if volume is not None:
        await async_set_volume(hass, media_player, volume)

    # Find a TTS entity if not specified
    if not tts_entity:
        tts_entity = await _find_tts_entity(hass, language)

    if not tts_entity:
        _LOGGER.error("No TTS entity found")
        return

    # Send TTS using the correct service call format
    try:
        await hass.services.async_call(
            "tts",
            "speak",
            {
                "media_player_entity_id": media_player,
                "message": message.strip(),
            },
            target={"entity_id": tts_entity},
            blocking=blocking,
        )
        _LOGGER.debug("TTS sent to %s via %s: %s", media_player, tts_entity, message[:50])

    except Exception as e:
        _LOGGER.error("Failed to send TTS: %s", e)
        raise


async def _find_tts_entity(hass: HomeAssistant, language: str | None = None) -> str | None:
    """Find an available TTS entity."""
    lang = language or DEFAULT_TTS_LANGUAGE
    
    # Look for TTS entities
    tts_entities = []
    for state in hass.states.async_all():
        if state.entity_id.startswith("tts."):
            tts_entities.append(state.entity_id)
    
    if not tts_entities:
        _LOGGER.warning("No TTS entities found in Home Assistant")
        return None

    # Try to find one matching the language
    for entity_id in tts_entities:
        if lang in entity_id.lower():
            return entity_id
    
    # Return first available
    return tts_entities[0] if tts_entities else None


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
            blocking=False,
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
