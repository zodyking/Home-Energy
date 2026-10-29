"""TTS helper functions for Smart Dashboards."""
from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant
from homeassistant.const import ATTR_ENTITY_ID

from .const import DEFAULT_TTS_LANGUAGE

_LOGGER = logging.getLogger(__name__)

# States that used to gate the queue. tts.speak is sent without waiting for these,
# because speakers often stay off, paused, or playing and that wait stacked announcements.
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

    # Set volume if specified. A volume failure must not block the announcement.
    if volume is not None:
        try:
            await async_set_volume(hass, media_player, volume)
        except Exception as err:
            _LOGGER.warning("Volume change failed for %s, speaking anyway: %s", media_player, err)

    # Find a TTS entity if not specified
    if not tts_entity:
        tts_entity = await _find_tts_entity(hass, language)

    if not tts_entity:
        _LOGGER.error("No TTS entity found")
        return

    # Every announcement uses tts.speak. Language is included when one is configured.
    service_data: dict = {
        "media_player_entity_id": media_player,
        "message": message.strip(),
    }
    if language:
        service_data["language"] = language

    try:
        await hass.services.async_call(
            "tts",
            "speak",
            service_data,
            target={"entity_id": tts_entity},
            blocking=blocking,
        )
        _LOGGER.debug("TTS sent to %s via %s: %s", media_player, tts_entity, message[:50])

    except Exception as e:
        _LOGGER.error("Failed to send TTS: %s", e)
        raise


async def _find_tts_entity(hass: HomeAssistant, language: str | None = None) -> str | None:
    """Find one TTS engine. Every announcement uses this entity with tts.speak."""
    lang = (language or DEFAULT_TTS_LANGUAGE).lower()

    available: list[str] = []
    fallback: list[str] = []
    for state in hass.states.async_all():
        if not state.entity_id.startswith("tts."):
            continue
        fallback.append(state.entity_id)
        if (state.state or "").lower() not in ("unavailable", "unknown"):
            available.append(state.entity_id)

    candidates = available or fallback
    if not candidates:
        _LOGGER.warning("No TTS entities found in Home Assistant")
        return None

    for entity_id in candidates:
        if lang in entity_id.lower():
            return entity_id
    return candidates[0]


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
