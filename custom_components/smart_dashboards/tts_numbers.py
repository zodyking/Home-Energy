"""Whole-number phrases for TTS (avoid engines reading 1038 as ten-thirty-eight)."""

from __future__ import annotations


def spoken_cardinal(n: float | int) -> str:
    """English cardinal for a rounded non-negative integer (TTS-friendly)."""
    try:
        v = int(round(float(n)))
    except (TypeError, ValueError):
        v = 0
    if v < 0:
        v = 0
    try:
        from num2words import num2words

        return num2words(v, lang="en", to="cardinal")
    except Exception:
        return str(v)


def watts_words(n: float | int) -> str:
    """Alias for watt/threshold values in spoken messages."""
    return spoken_cardinal(n)
