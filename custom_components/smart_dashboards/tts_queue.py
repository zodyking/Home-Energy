"""TTS queue: one in-flight announcement per speaker, newest waiting call only."""
from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable

from homeassistant.core import HomeAssistant

from .tts_helper import async_send_tts

_LOGGER = logging.getLogger(__name__)

# Poll interval when media player is not ready
POLL_INTERVAL = 1.0
# Minimum seconds between TTS sends per media player (prevents rapid-fire hang)
MIN_TTS_INTERVAL = 3.0
# A queued announcement older than this is deleted instead of spoken late.
MAX_QUEUE_AGE = 15.0


@dataclass
class TTSPendingItem:
    """One announcement waiting for this speaker to finish the call already in flight."""

    media_player: str
    message: str
    language: str | None
    volume: float | None
    tts_entity: str | None
    room: dict | None  # For responsive lights
    tts_settings: dict
    with_lights_callback: Callable[[], Awaitable[None]] | None  # Optional lights+tts call
    post_send_callback: Callable[[], Awaitable[None]] | None = None  # Run after TTS actually sent (incl. when from queue)
    blocking: bool = False
    queued_at: float = field(default_factory=time.monotonic)


class TTSPendingQueue:
    """Per-media-player queue. Holds the newest waiting call and drops it if it goes stale."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._queues: dict[str, list[TTSPendingItem]] = defaultdict(list)
        self._poll_tasks: dict[str, asyncio.Task] = {}
        self._lock = asyncio.Lock()
        self._sending: set[str] = set()  # Media players currently sending TTS (prevents concurrent sends)
        self._last_send_time: dict[str, float] = {}  # media_player -> monotonic time of last send

    async def enqueue(self, item: TTSPendingItem) -> None:
        """Keep only the newest announcement per player. Older queued calls are deleted."""
        async with self._lock:
            waiting = self._queues[item.media_player]
            if waiting:
                _LOGGER.info(
                    "Dropped %s queued TTS message(s) for %s; a newer announcement replaced them",
                    len(waiting),
                    item.media_player,
                )
            self._queues[item.media_player] = [item]
            task = self._poll_tasks.get(item.media_player)
            if task is None or task.done():
                self._poll_tasks[item.media_player] = asyncio.create_task(
                    self._poll_until_ready(item.media_player)
                )
        for old in waiting:
            if item.post_send_callback is None:
                self._schedule_follow_up(old)

    def _schedule_follow_up(self, item: TTSPendingItem) -> None:
        """Run a dropped announcement's outlet action without speaking the stale line."""
        if item.post_send_callback is None:
            return
        asyncio.create_task(self._run_follow_up(item))

    async def _run_follow_up(self, item: TTSPendingItem) -> None:
        try:
            if item.post_send_callback:
                await item.post_send_callback()
        except Exception as err:
            _LOGGER.error("TTS follow-up failed for %s: %s", item.media_player, err)

    async def _poll_until_ready(self, media_player: str) -> None:
        """Speak the newest fresh announcement as soon as this player is free. Drop anything older."""
        try:
            while True:
                await asyncio.sleep(POLL_INTERVAL)
                async with self._lock:
                    queue = self._queues[media_player]
                    if not queue:
                        self._poll_tasks.pop(media_player, None)
                        return
                    item = queue[0]
                    age = time.monotonic() - item.queued_at
                    if age > MAX_QUEUE_AGE:
                        queue.pop(0)
                        expired: TTSPendingItem | None = item
                        send_item: TTSPendingItem | None = None
                    else:
                        expired = None
                        settings = item.tts_settings or {}
                        min_interval = float(
                            settings.get("min_interval_seconds", MIN_TTS_INTERVAL)
                        )
                        if not self._can_send_now(media_player, min_interval):
                            continue
                        if not queue or queue[0] is not item:
                            continue
                        queue.pop(0)
                        self._sending.add(media_player)
                        send_item = item
                if expired is not None:
                    _LOGGER.info(
                        "Dropped expired TTS for %s (queued %.0fs ago)",
                        media_player,
                        age,
                    )
                    self._schedule_follow_up(expired)
                    continue
                if send_item is None:
                    continue
                try:
                    await self._send_item(send_item)
                except Exception as err:
                    _LOGGER.error("TTS queue send failed for %s: %s", media_player, err)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            _LOGGER.error("TTS queue poll error for %s: %s", media_player, e)

    def _can_send_now(self, media_player: str, min_interval: float = MIN_TTS_INTERVAL) -> bool:
        """Return True if no TTS is in progress and min interval has passed."""
        if media_player in self._sending:
            return False
        last = self._last_send_time.get(media_player)
        if last is not None and (time.monotonic() - last) < min_interval:
            return False
        return True

    async def _send_item(self, item: TTSPendingItem) -> None:
        """Speak one item. The player is already marked sending by the caller."""
        callback_error: Exception | None = None
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
            self._last_send_time[item.media_player] = time.monotonic()
        except Exception as e:
            _LOGGER.error("TTS queue send failed for %s: %s", item.media_player, e)
        finally:
            self._sending.discard(item.media_player)
        if item.post_send_callback:
            try:
                await item.post_send_callback()
            except Exception as err:
                callback_error = err
        if callback_error:
            _LOGGER.error(
                "TTS follow-up failed for %s: %s", item.media_player, callback_error
            )


# Module-level queue instance (set when integration starts)
_tts_queue: TTSPendingQueue | None = None


def get_tts_queue(hass: HomeAssistant) -> TTSPendingQueue:
    """Get or create the global TTS queue."""
    global _tts_queue
    if _tts_queue is None:
        _tts_queue = TTSPendingQueue(hass)
    return _tts_queue


async def async_reset_tts_queue() -> None:
    """Cancel poll tasks and reset the global TTS queue on integration unload."""
    global _tts_queue
    if _tts_queue is not None:
        for task in list(_tts_queue._poll_tasks.values()):
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        _tts_queue._poll_tasks.clear()
        _tts_queue._queues.clear()
    _tts_queue = None


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
    post_send_callback: Callable[[], Awaitable[None]] | None = None,
    blocking: bool = False,
) -> bool:
    """
    Speak now unless this player already has a call in flight or inside the short gap.
    A call that cannot go out yet replaces any older waiting call for that player.
    A waiting call older than MAX_QUEUE_AGE is deleted and never spoken.
    post_send_callback runs after TTS is actually sent (when immediate or when dequeued).
    Returns True if sent immediately, False if enqueued.
    """
    if not message or not message.strip():
        _LOGGER.warning("Empty TTS message, skipping")
        return False
    if not media_player:
        _LOGGER.warning("No media player specified for TTS")
        return False

    queue = get_tts_queue(hass)
    min_interval = float(tts_settings.get("min_interval_seconds", MIN_TTS_INTERVAL)) if tts_settings else MIN_TTS_INTERVAL

    async with queue._lock:
        send_now = queue._can_send_now(media_player, min_interval)
        if send_now:
            queue._sending.add(media_player)
    if send_now:
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
            queue._last_send_time[media_player] = time.monotonic()
        except Exception as e:
            _LOGGER.error("TTS send failed: %s", e)
            raise
        finally:
            queue._sending.discard(media_player)
        if post_send_callback:
            await post_send_callback()
        return True

    item = TTSPendingItem(
        media_player=media_player,
        message=message,
        language=language,
        volume=volume,
        tts_entity=tts_entity,
        room=room,
        tts_settings=tts_settings or {},
        with_lights_callback=with_lights_callback,
        post_send_callback=post_send_callback,
        blocking=blocking,
    )
    await queue.enqueue(item)
    _LOGGER.debug("TTS waiting for %s (speaker busy or inside the short gap)", media_player)
    return False
