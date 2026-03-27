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
DEFAULT_ROOM_WARN_MSG = "{prefix} {room_name} is using {watts} watts out of {threshold} watt room threshold, reduce your usage."
DEFAULT_OUTLET_WARN_MSG = "{prefix} {outlet_name} in {room_name} is using {watts} watts out of {threshold} watt outlet threshold, reduce your usage."
DEFAULT_SHUTOFF_MSG = "{prefix} {room_name} {outlet_name} {plug} reset after overload, reduce power use."
DEFAULT_BREAKER_WARN_MSG = "{prefix} {breaker_name} is using {watts} watts out of {max_load} watt limit, reduce your usage."
DEFAULT_BREAKER_SHUTOFF_MSG = "{prefix} {breaker_name} at limit, {watts} watts, max {max_load} watts. Shutoff enabled."
DEFAULT_STOVE_ON_MSG = "{prefix} Stove has been turned on"
DEFAULT_STOVE_OFF_MSG = "{prefix} Stove has been turned off"
DEFAULT_STOVE_TIMER_STARTED_MSG = "{prefix} The stove is on with no one in the kitchen. A {cooking_time_minutes} minute Unattended cooking timer has started."
DEFAULT_STOVE_15MIN_WARN_MSG = "{prefix} Stove has been on for {cooking_time_minutes} minutes with no one in the kitchen. Stove will automatically turn off in {final_warning_seconds} seconds if no one returns"
DEFAULT_STOVE_30SEC_WARN_MSG = "{prefix} Stove will automatically turn off in {final_warning_seconds} seconds if no one returns to the kitchen"
DEFAULT_STOVE_AUTO_OFF_MSG = "{prefix} Stove has been automatically turned off for safety"
DEFAULT_STOVE_TIMER_PROGRESS_MSG = (
    "{prefix} Stove unattended timer: about {minutes_remaining} minutes "
    "and {seconds_remaining} seconds remaining."
)
DEFAULT_MICROWAVE_CUT_MSG = "{prefix} Microwave is on. Stove power cut to protect circuit. Power will restore when microwave is off."
DEFAULT_MICROWAVE_RESTORE_MSG = "{prefix} Microwave is off. Stove power restored."

# Power enforcement TTS messages (flow naturally after prefix "Message from Home Energy.")
DEFAULT_PHASE1_WARN_MSG = "{prefix} {room_name} has exceeded threshold {warning_count} times. Volume will rise until power stays under {threshold} watts."
DEFAULT_PHASE2_WARN_MSG = "{prefix} {room_name} has exceeded threshold {warning_count} times. Cycling all outlets now, turn off devices."
DEFAULT_PHASE2_AFTER_MSG = "{prefix} Cycle complete in {room_name}. Stay under limit or outlets cycle again."
DEFAULT_MINISPLIT_PHASE2_WARN_MSG = (
    "{prefix} {room_name} is over the {room_threshold} watt room limit. "
    "Turning off {outlet_name} to protect the circuit. It will stay off at least {restore_delay} seconds for compressor safety, "
    "and will only turn back on when the room is under the limit. Other outlets may still cycle if the room stays high."
)
DEFAULT_MINISPLIT_PHASE2_AFTER_MSG = (
    "{prefix} Enforcement step complete in {room_name}. "
    "{outlet_name} stays off until total room power is under {room_threshold} watts."
)
DEFAULT_MINISPLIT_PHASE2_RESTORE_MSG = (
    "{prefix} Room power is under {room_threshold} watts. Restoring power to {outlet_name}."
)
DEFAULT_PHASE_RESET_MSG = "{prefix} {room_name} under limit, enforcement reset."
DEFAULT_ROOM_KWH_WARN_MSG = "{prefix} {room_name} used {kwh_limit} kWh today, {percentage} percent of home, reduce use."
DEFAULT_HOME_KWH_WARN_MSG = "{prefix} Home over {kwh_limit} kWh today, reduce consumption."
DEFAULT_BUDGET_EXCEEDED_MSG = "{prefix} {room_name} at {kwh_used} kWh, power alerts are on."
DEFAULT_BUDGET_BOOST_SCHEDULED_MSG = (
    "{prefix} Room kilo watt hour budgets are {budget_multiplier} times higher {period_label}, "
    "because usage is usually higher those days."
)
DEFAULT_PHASE1_WARN_BOOST_DAY_MSG = (
    "{prefix} {room_name} has exceeded threshold {warning_count} times. "
    "Kilo watt hour budget is {budget_multiplier} times higher {period_label}, "
    "effective {kwh_budget_effective} versus usual {kwh_budget} kilo watt hours. "
    "Volume will rise until power stays under {threshold} watts."
)
DEFAULT_HEATER_AUTOMATION_ON_MSG = (
    "{prefix} {room_name} temp below {threshold} degrees, warming up {room_name}."
)
DEFAULT_VENT_AUTOMATION_ON_MSG = (
    "{prefix} {room_name} vent is on."
)

# Notification message templates (for mobile push notifications)
DEFAULT_NOTIFICATION_TITLE = "Home Energy"
DEFAULT_NOTIFY_BUDGET_HIT_TITLE = "{notification_title} Budget Exceeded"
DEFAULT_NOTIFY_BUDGET_HIT_MSG = "{room_name} has exceeded its daily budget of {kwh_budget} kWh (used {kwh_used} kWh)."
DEFAULT_NOTIFY_ENFORCEMENT_PHASE1_TITLE = "{notification_title} Enforcement Phase 1"
DEFAULT_NOTIFY_ENFORCEMENT_PHASE1_MSG = "{room_name} has entered enforcement phase 1 (volume escalation). Please reduce power usage."
DEFAULT_NOTIFY_ENFORCEMENT_PHASE2_TITLE = "{notification_title} Enforcement Phase 2"
DEFAULT_NOTIFY_ENFORCEMENT_PHASE2_MSG = "{room_name} has entered enforcement phase 2 (power cycling). Please reduce power usage."
DEFAULT_NOTIFY_AC_AUTO_OFF_TITLE = "{notification_title} Air Conditioner Off"
DEFAULT_NOTIFY_AC_AUTO_OFF_MSG = (
    "{outlet_name} was turned off because {person_name} left the monitored zone."
)
DEFAULT_NOTIFY_AC_AUTO_ON_TITLE = "{notification_title} Air Conditioner On"
DEFAULT_NOTIFY_AC_AUTO_ON_MSG = (
    "{outlet_name} was turned back on because {person_name} is nearby."
)
DEFAULT_NOTIFY_MANUAL_TOGGLE_TITLE = "{notification_title} Appliance Toggled"
DEFAULT_NOTIFY_MANUAL_TOGGLE_MSG = "{user_name} turned {action} {outlet_name} in {room_name}."

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
            "phase2_after_msg": DEFAULT_PHASE2_AFTER_MSG,
            "minisplit_phase2_warn_msg": DEFAULT_MINISPLIT_PHASE2_WARN_MSG,
            "minisplit_phase2_after_msg": DEFAULT_MINISPLIT_PHASE2_AFTER_MSG,
            "minisplit_phase2_restore_msg": DEFAULT_MINISPLIT_PHASE2_RESTORE_MSG,
            "phase_reset_msg": DEFAULT_PHASE_RESET_MSG,
            "room_kwh_warn_msg": DEFAULT_ROOM_KWH_WARN_MSG,
            "home_kwh_warn_msg": DEFAULT_HOME_KWH_WARN_MSG,
            "budget_exceeded_msg": DEFAULT_BUDGET_EXCEEDED_MSG,
            "min_interval_seconds": 3,
            "tts_default_media_player": "",
            "budget_boost_enabled": False,
            "budget_boost_multiplier": 2.0,
            "budget_boost_weekdays": [5, 6],
            "budget_boost_window_start": "09:00",
            "budget_boost_window_end": "21:00",
            "budget_boost_repeat_minutes": 120,
            "budget_boost_minute_offset": 0,
            "budget_boost_announce_time": "09:00",
            "budget_boost_announce_media_player": "",
            "budget_boost_scheduled_msg": DEFAULT_BUDGET_BOOST_SCHEDULED_MSG,
            "phase1_warn_msg_boost_day": DEFAULT_PHASE1_WARN_BOOST_DAY_MSG,
            "stove_timer_progress_msg": DEFAULT_STOVE_TIMER_PROGRESS_MSG,
            "heater_automation_tts_enabled": False,
            "vent_automation_tts_enabled": False,
            "heater_automation_on_msg": DEFAULT_HEATER_AUTOMATION_ON_MSG,
            "vent_automation_on_msg": DEFAULT_VENT_AUTOMATION_ON_MSG,
            "room_warn_tts_enabled": True,
            "outlet_warn_tts_enabled": True,
            "budget_exceeded_tts_enabled": True,
            "budget_boost_scheduled_tts_enabled": True,
            "phase1_warn_boost_day_tts_enabled": True,
            "shutoff_tts_enabled": True,
            "stove_on_tts_enabled": True,
            "stove_off_tts_enabled": True,
            "stove_timer_started_tts_enabled": True,
            "stove_timer_progress_tts_enabled": True,
            "stove_15min_warn_tts_enabled": True,
            "stove_30sec_warn_tts_enabled": True,
            "stove_auto_off_tts_enabled": True,
            "phase1_warn_tts_enabled": True,
            "phase2_warn_tts_enabled": True,
            "phase2_after_tts_enabled": True,
            "minisplit_phase2_warn_tts_enabled": True,
            "minisplit_phase2_after_tts_enabled": True,
            "minisplit_phase2_restore_tts_enabled": True,
            "phase_reset_tts_enabled": True,
            "room_kwh_warn_tts_enabled": True,
            "home_kwh_warn_tts_enabled": True,
            "notifications_enabled": False,
            "notify_room_budget_hit": True,
            "notify_enforcement_phase_change": True,
            "notify_ac_auto_off": True,
            "notify_ac_auto_on": True,
            "notify_person_toggle": True,
            "notify_integration_auto": True,
            "notify_external_auto": True,
            "notification_title": DEFAULT_NOTIFICATION_TITLE,
            "notify_budget_hit_title": DEFAULT_NOTIFY_BUDGET_HIT_TITLE,
            "notify_budget_hit_msg": DEFAULT_NOTIFY_BUDGET_HIT_MSG,
            "notify_enforcement_phase1_title": DEFAULT_NOTIFY_ENFORCEMENT_PHASE1_TITLE,
            "notify_enforcement_phase1_msg": DEFAULT_NOTIFY_ENFORCEMENT_PHASE1_MSG,
            "notify_enforcement_phase2_title": DEFAULT_NOTIFY_ENFORCEMENT_PHASE2_TITLE,
            "notify_enforcement_phase2_msg": DEFAULT_NOTIFY_ENFORCEMENT_PHASE2_MSG,
            "notify_ac_auto_off_title": DEFAULT_NOTIFY_AC_AUTO_OFF_TITLE,
            "notify_ac_auto_off_msg": DEFAULT_NOTIFY_AC_AUTO_OFF_MSG,
            "notify_ac_auto_on_title": DEFAULT_NOTIFY_AC_AUTO_ON_TITLE,
            "notify_ac_auto_on_msg": DEFAULT_NOTIFY_AC_AUTO_ON_MSG,
            "notify_toggle_title": DEFAULT_NOTIFY_MANUAL_TOGGLE_TITLE,
            "notify_toggle_msg": DEFAULT_NOTIFY_MANUAL_TOGGLE_MSG,
        },
        "power_enforcement": {
            "enabled": False,
            "phase1_enabled": True,
            "phase2_enabled": True,
            "phase1_warning_count": 20,
            "phase1_time_window_minutes": 60,
            "phase1_volume_increment": 2,
            "phase1_reset_minutes": 60,
            "phase2_warning_count": 10,
            "phase2_time_window_minutes": 10,
            "phase2_reset_minutes": 30,
            "phase2_cycle_delay_seconds": 5,
            "phase2_max_volume": 100,
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
            "statistics_refresh_seconds": 60,
        },
    },
}
