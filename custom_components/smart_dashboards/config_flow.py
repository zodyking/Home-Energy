"""Config flow for Home Energy integration."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
import logging

from .const import DOMAIN, NAME

_LOGGER = logging.getLogger(__name__)


class SmartDashboardsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Home Energy."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        errors: dict[str, str] = {}

        if user_input is not None:
            passcode = str(user_input.get("settings_passcode", ""))
            if not passcode.isdigit() or len(passcode) != 4:
                errors["settings_passcode"] = "invalid_passcode"
            else:
                return self.async_create_entry(
                    title=NAME,
                    data={},
                    options={
                        "enable_energy": True,
                        "settings_passcode": passcode,
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required("settings_passcode"): str,
            }),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reconfiguration to change settings passcode."""
        errors: dict[str, str] = {}
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])

        if user_input is not None:
            passcode = str(user_input.get("settings_passcode", ""))
            if not passcode.isdigit() or len(passcode) != 4:
                errors["settings_passcode"] = "invalid_passcode"
            else:
                return self.async_update_reload_and_abort(
                    entry,
                    options={**entry.options, "settings_passcode": passcode},
                )

        current = entry.options.get("settings_passcode", "") if entry else ""
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema({
                vol.Required("settings_passcode", default=current): str,
            }),
            errors=errors,
        )
