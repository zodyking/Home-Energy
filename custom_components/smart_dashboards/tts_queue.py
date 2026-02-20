"""TTS queue: wait for media player to be ready (on/idle/standby) before sending."""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable

from homeassistant.core import HomeAssistant

from .tts_helper import async_send_tts, is_media_player_ready_for_tts

_LOGGER = logging.getLogger(__name__)

# Poll interval when media player is not ready
POLL_INTERVAL = 1.0


@dataclass
class TTSPendingItem:
    """A pending TTS message waiting for media player to be ready."""

    media_player: str
    message: str
    language: str | None
    volume: float | None
    tts_entity: str | None
    room: dict | None  # For responsive lights
    tts_settings: dict
    with_lights_callback: Callable[[], Awaitable[None]] | None  # Optional lights+tts call
    blocking: bool = False


class TTSPendingQueue:
    """Per-media-player queue; polls every second and sends when player is ready."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._queues: dict[str, list[TTSPendingItem]] = defaultdict(list)
        self._poll_tasks: dict[str, asyncio.Task] = {}
        self._lock = asyncio.Lock()

    async def enqueue(self, item: TTSPendingItem) -> None:
        """Add item to queue for its media player; start poll task if needed."""
        async with self._lock:
            self._queues[item.media_player].append(item)
            if item.media_player not in self._poll_tasks or self._poll_tasks[
                item.media_player
            ].done():
                self._poll_tasks[item.media_player] = asyncio.create_task(
                    self._poll_until_ready(item.media_player)
                )

    async def _poll_until_ready(self, media_player: str) -> None:
        """Poll every second; when ready, send next item and re-queue or stop."""
        try:
            while True:
                await asyncio.sleep(POLL_INTERVAL)
                async with self._lock:
                    queue = self._queues[media_player]
                    if not queue:
                        self._poll_tasks.pop(media_player, None)
                        return
                    if not is_media_player_ready_for_tts(self.hass, media_player):
                        continue
                    item = queue.pop(0)
                # Send outside lock to avoid blocking
                await self._send_item(item)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            _LOGGER.error("TTS queue poll error for %s: %s", media_player, e)

    async def _send_item(self, item: TTSPendingItem) -> None:
        """Send a single TTS item (with optional lights callback)."""
        try:
            if item.with_lights_callback:
                await item.with_lights_callback()
            else:
                await async_send_tts(
                    self.hass,
                    media_player=item.media_player,
                    message=item.message,
                    language=item.language,
                    volume=item.volume,
                    tts_entity=item.tts_entity,
                    blocking=item.blocking,
                )
        except Exception as e:
            _LOGGER.error("TTS queue send failed for %s: %s", item.media_player, e)
            raise


# Module-level queue instance (set when integration starts)
_tts_queue: TTSPendingQueue | None = None


def get_tts_queue(hass: HomeAssistant) -> TTSPendingQueue:
    """Get or create the global TTS queue."""
    global _tts_queue
    if _tts_queue is None:
        _tts_queue = TTSPendingQueue(hass)
    return _tts_queue


async def async_send_tts_or_queue(
    hass: HomeAssistant,
    media_player: str,
    message: str,
    language: str | None = None,
    volume: float | None = None,
    tts_entity: str | None = None,
    room: dict | None = None,
    tts_settings: dict | None = None,
    with_lights_callback: Callable[[], Awaitable[None]] | None = None,
    blocking: bool = False,
) -> bool:
    """
    Send TTS immediately if media player is ready (on, idle, standby).
    Otherwise enqueue and poll until ready.
    Returns True if sent immediately, False if enqueued.
    """
    if not message or not message.strip():
        _LOGGER.warning("Empty TTS message, skipping")
        return False
    if not media_player:
        _LOGGER.warning("No media player specified for TTS")
        return False

    if is_media_player_ready_for_tts(hass, media_player):
        try:
            if with_lights_callback:
                await with_lights_callback()
            else:
                await async_send_tts(
                    hass,
                    media_player=media_player,
                    message=message,
                    language=language,
                    volume=volume,
                    tts_entity=tts_entity,
                    blocking=blocking,
                )
            return True
        except Exception as e:
            _LOGGER.error("TTS send failed: %s", e)
            raise

    item = TTSPendingItem(
        media_player=media_player,
        message=message,
        language=language,
        volume=volume,
        tts_entity=tts_entity,
        room=room,
        tts_settings=tts_settings or {},
        with_lights_callback=with_lights_callback,
        blocking=blocking,
    )
    queue = get_tts_queue(hass)
    await queue.enqueue(item)
    _LOGGER.debug("TTS enqueued for %s (player not ready)", media_player)
    return False
