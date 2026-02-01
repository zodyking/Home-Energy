"""Constants for Smart Dashboards integration."""
from __future__ import annotations

DOMAIN = "smart_dashboards"
NAME = "Smart Dashboards"

# Config file
CONFIG_FILE = "smart_dashboards.json"

# Panel configuration
CAMERAS_PANEL_ICON = "mdi:cctv"
CAMERAS_PANEL_TITLE = "Cameras"
CAMERAS_PANEL_URL = "smart-dashboards-cameras"

ENERGY_PANEL_ICON = "mdi:flash"
ENERGY_PANEL_TITLE = "Home Energy"
ENERGY_PANEL_URL = "smart-dashboards-energy"

# Default TTS settings
DEFAULT_TTS_LANGUAGE = "en"
DEFAULT_TTS_SPEED = 1.0
DEFAULT_TTS_VOLUME = 0.7

# Energy monitor settings
ENERGY_CHECK_INTERVAL = 1  # seconds
ALERT_COOLDOWN = 60  # seconds between repeated alerts for same room

# Default config structure
DEFAULT_CONFIG = {
    "cameras": {
        "main_camera": None,
        "sub_cameras": [],
        "tts_settings": {
            "language": DEFAULT_TTS_LANGUAGE,
            "speed": DEFAULT_TTS_SPEED,
            "volume": DEFAULT_TTS_VOLUME,
        },
    },
    "energy": {
        "rooms": [],
        "tts_settings": {
            "language": DEFAULT_TTS_LANGUAGE,
            "speed": DEFAULT_TTS_SPEED,
            "volume": DEFAULT_TTS_VOLUME,
        },
    },
}
