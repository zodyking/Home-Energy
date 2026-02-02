"""Constants for Smart Dashboards integration."""
from __future__ import annotations

DOMAIN = "smart_dashboards"
NAME = "Home Energy"

# Config file
CONFIG_FILE = "smart_dashboards.json"

# Panel configuration
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

# Stove safety defaults (user can override in config)
STOVE_WARNING_TIMER = 900  # 15 minutes in seconds
STOVE_SHUTOFF_TIMER = 30  # 30 seconds

# TTS message templates (user customizable)
DEFAULT_TTS_PREFIX = "Message from Home Energy."
DEFAULT_ROOM_WARN_MSG = "{prefix} {room_name} is pulling {watts} watts"
DEFAULT_OUTLET_WARN_MSG = "{prefix} {room_name} {outlet_name} is pulling {watts} watts"
DEFAULT_SHUTOFF_MSG = "{prefix} {room_name} {outlet_name} {plug} has been reset to protect circuit from overload"
DEFAULT_BREAKER_WARN_MSG = "{prefix} {breaker_name} is near its max load, reduce electric use to prevent safety shutoff"
DEFAULT_BREAKER_SHUTOFF_MSG = "{prefix} {breaker_name} is currently at its max limit, safety shutoff enabled"
DEFAULT_STOVE_ON_MSG = "{prefix} Stove has been turned on"
DEFAULT_STOVE_OFF_MSG = "{prefix} Stove has been turned off"
DEFAULT_STOVE_TIMER_STARTED_MSG = "{prefix} The stove is on with no one in the kitchen. A {cooking_time_minutes} minute Unattended cooking timer has started."
DEFAULT_STOVE_15MIN_WARN_MSG = "{prefix} Stove has been on for {cooking_time_minutes} minutes with no one in the kitchen. Stove will automatically turn off in {final_warning_seconds} seconds if no one returns"
DEFAULT_STOVE_30SEC_WARN_MSG = "{prefix} Stove will automatically turn off in {final_warning_seconds} seconds if no one returns to the kitchen"
DEFAULT_STOVE_AUTO_OFF_MSG = "{prefix} Stove has been automatically turned off for safety"
DEFAULT_MICROWAVE_CUT_MSG = "{prefix} Microwave is on. Stove power cut to protect circuit. Power will restore when microwave is off."
DEFAULT_MICROWAVE_RESTORE_MSG = "{prefix} Microwave is off. Stove power restored."

# Default config structure
DEFAULT_CONFIG = {
    "energy": {
        "rooms": [],
        "breaker_lines": [],
        "stove_safety": {
            "stove_plug_entity": None,
            "stove_plug_switch": None,
            "stove_power_threshold": 100,
            "cooking_time_minutes": 15,
            "final_warning_seconds": 30,
            "presence_sensor": None,
            "media_player": None,
            "volume": DEFAULT_TTS_VOLUME,
            "microwave_plug_entity": None,
            "microwave_power_threshold": 50,
        },
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
            "stove_on_msg": DEFAULT_STOVE_ON_MSG,
            "stove_off_msg": DEFAULT_STOVE_OFF_MSG,
            "stove_timer_started_msg": DEFAULT_STOVE_TIMER_STARTED_MSG,
            "stove_15min_warn_msg": DEFAULT_STOVE_15MIN_WARN_MSG,
            "stove_30sec_warn_msg": DEFAULT_STOVE_30SEC_WARN_MSG,
            "stove_auto_off_msg": DEFAULT_STOVE_AUTO_OFF_MSG,
            "microwave_cut_power_msg": DEFAULT_MICROWAVE_CUT_MSG,
            "microwave_restore_power_msg": DEFAULT_MICROWAVE_RESTORE_MSG,
        },
    },
}
