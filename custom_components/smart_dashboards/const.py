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

# Power enforcement TTS messages
DEFAULT_PHASE1_WARN_MSG = "{prefix} {room_name} has hit {warning_count} threshold warnings within the hour. Threshold warning volume will increase systematically until {room_name} power remains below its consumption threshold of {threshold} watts for an hour."
DEFAULT_PHASE2_WARN_MSG = "{prefix} {room_name} has hit {warning_count} threshold warnings within 30 minutes. Please reduce power consumption by turning off minor appliances or lights. Each ongoing consumption warning will systematically power cycle your outlet plugs with the least power usage to help reduce the load."
DEFAULT_PHASE_RESET_MSG = "{prefix} {room_name} has maintained power below threshold for the required time. Power enforcement has been reset to normal."
DEFAULT_ROOM_KWH_WARN_MSG = "{prefix} {room_name} has exceeded {kwh_limit} kilowatt hours for the day. Please reduce power consumption by powering off unused devices. This room has contributed to {percentage} percent of the entire home's usage for the day."
DEFAULT_HOME_KWH_WARN_MSG = "{prefix} Your home has exceeded {kwh_limit} kilowatt hours for the day. This is above average household usage in New York City. Please reduce power consumption."

# Default config structure
DEFAULT_CONFIG = {
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
            "stove_on_msg": DEFAULT_STOVE_ON_MSG,
            "stove_off_msg": DEFAULT_STOVE_OFF_MSG,
            "stove_timer_started_msg": DEFAULT_STOVE_TIMER_STARTED_MSG,
            "stove_15min_warn_msg": DEFAULT_STOVE_15MIN_WARN_MSG,
            "stove_30sec_warn_msg": DEFAULT_STOVE_30SEC_WARN_MSG,
            "stove_auto_off_msg": DEFAULT_STOVE_AUTO_OFF_MSG,
            "microwave_cut_power_msg": DEFAULT_MICROWAVE_CUT_MSG,
            "microwave_restore_power_msg": DEFAULT_MICROWAVE_RESTORE_MSG,
            "phase1_warn_msg": DEFAULT_PHASE1_WARN_MSG,
            "phase2_warn_msg": DEFAULT_PHASE2_WARN_MSG,
            "phase_reset_msg": DEFAULT_PHASE_RESET_MSG,
            "room_kwh_warn_msg": DEFAULT_ROOM_KWH_WARN_MSG,
            "home_kwh_warn_msg": DEFAULT_HOME_KWH_WARN_MSG,
        },
        "power_enforcement": {
            "enabled": False,
            "phase1_warning_count": 20,
            "phase1_time_window_minutes": 60,
            "phase1_volume_increment": 2,
            "phase1_reset_minutes": 60,
            "phase2_warning_count": 40,
            "phase2_time_window_minutes": 30,
            "phase2_reset_minutes": 30,
            "phase2_cycle_delay_seconds": 5,
            "room_kwh_intervals": [5, 10, 15, 20],
            "home_kwh_limit": 22,
            "rooms_enabled": [],
        },
        "statistics_settings": {
            "billing_start_sensor": "",
            "billing_end_sensor": "",
            "current_usage_sensor": "",
            "projected_usage_sensor": "",
            "kwh_cost_sensor": "",
        },
    },
}
