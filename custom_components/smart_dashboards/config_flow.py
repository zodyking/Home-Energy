"""Config flow for Smart Dashboards integration."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow, ConfigEntry
from homeassistant.core import callback
import logging

from .const import DOMAIN, NAME

_LOGGER = logging.getLogger(__name__)


class SmartDashboardsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Smart Dashboards."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Get the options flow for this handler."""
        return SmartDashboardsOptionsFlow(config_entry)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reconfigure step (same as options: panels + passcode)."""
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        if entry is None:
            return self.async_abort(reason="entry_not_found")

        errors = {}

        if user_input is not None:
            passcode = user_input.get("settings_passcode", "")
            if not passcode.isdigit() or len(passcode) != 4:
                errors["settings_passcode"] = "invalid_passcode"
            else:
                self.hass.config_entries.async_update_entry(
                    entry, data={}, options=user_input
                )
                return self.async_abort(reason="reconfigure_successful")

        current = entry.options or {}
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema({
                vol.Required(
                    "enable_cameras",
                    default=current.get("enable_cameras", True),
                ): bool,
                vol.Required(
                    "enable_energy",
                    default=current.get("enable_energy", True),
                ): bool,
                vol.Required(
                    "settings_passcode",
                    default=current.get("settings_passcode", "0000"),
                ): str,
            }),
            errors=errors,
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        # Only allow one instance
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        errors = {}

        if user_input is not None:
            # Validate passcode is 4 digits
            passcode = user_input.get("settings_passcode", "")
            if not passcode.isdigit() or len(passcode) != 4:
                errors["settings_passcode"] = "invalid_passcode"
            else:
                return self.async_create_entry(
                    title=NAME,
                    data={},
                    options={
                        "enable_cameras": user_input.get("enable_cameras", True),
                        "enable_energy": user_input.get("enable_energy", True),
                        "settings_passcode": passcode,
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required("enable_cameras", default=True): bool,
                vol.Required("enable_energy", default=True): bool,
                vol.Required("settings_passcode"): str,
            }),
            errors=errors,
        )


class SmartDashboardsOptionsFlow(OptionsFlow):
    """Handle options flow for Smart Dashboards."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        errors = {}

        if user_input is not None:
            # Validate passcode is 4 digits
            passcode = user_input.get("settings_passcode", "")
            if not passcode.isdigit() or len(passcode) != 4:
                errors["settings_passcode"] = "invalid_passcode"
            else:
                # OptionsFlow: async_create_entry accepts data only (no title)
                return self.async_create_entry(data=user_input)

        # Get current options (handle case where options might not exist)
        current = self.config_entry.options or {}

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required(
                    "enable_cameras",
                    default=current.get("enable_cameras", True)
                ): bool,
                vol.Required(
                    "enable_energy",
                    default=current.get("enable_energy", True)
                ): bool,
                vol.Required(
                    "settings_passcode",
                    default=current.get("settings_passcode", "0000")
                ): str,
            }),
            errors=errors,
        )
