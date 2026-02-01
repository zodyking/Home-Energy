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
SHUTOFF_RESET_DELAY = 5  # seconds to wait before turning plug back on

# TTS message templates (user customizable)
DEFAULT_TTS_PREFIX = "Message from Home Energy."
DEFAULT_ROOM_WARN_MSG = "{prefix} {room_name} is pulling {watts} watts"
DEFAULT_OUTLET_WARN_MSG = "{prefix} {room_name} {outlet_name} is pulling {watts} watts"
DEFAULT_SHUTOFF_MSG = "{prefix} {room_name} {outlet_name} {plug} has been reset to protect circuit from overload"
DEFAULT_BREAKER_WARN_MSG = "{prefix} {breaker_name} is near its max load, reduce electric use to prevent safety shutoff"
DEFAULT_BREAKER_SHUTOFF_MSG = "{prefix} {breaker_name} is currently at its max limit, safety shutoff enabled"

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
        "breaker_lines": [],
        "tts_settings": {
            "language": DEFAULT_TTS_LANGUAGE,
            "speed": DEFAULT_TTS_SPEED,
            "volume": DEFAULT_TTS_VOLUME,
            "prefix": DEFAULT_TTS_PREFIX,
            "room_warn_msg": DEFAULT_ROOM_WARN_MSG,
            "outlet_warn_msg": DEFAULT_OUTLET_WARN_MSG,
            "shutoff_msg": DEFAULT_SHUTOFF_MSG,
            "breaker_warn_msg": DEFAULT_BREAKER_WARN_MSG,
            "breaker_shutoff_msg": DEFAULT_BREAKER_SHUTOFF_MSG,
        },
    },
}
