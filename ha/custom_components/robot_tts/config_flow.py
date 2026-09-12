"""Config and options flow for Robot TTS."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback

from .const import (
    CONF_PIPER_HOST,
    CONF_PIPER_PORT,
    CONF_ROBOT_ENABLED,
    CONF_ROBOT_FILTER,
    CONF_VOICE_EN,
    CONF_VOICE_RU,
    DEFAULT_PIPER_HOST,
    DEFAULT_PIPER_PORT,
    DEFAULT_ROBOT_FILTER,
    DEFAULT_VOICE_EN,
    DEFAULT_VOICE_RU,
    DOMAIN,
)


def _schema(d: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_PIPER_HOST, default=d.get(CONF_PIPER_HOST, DEFAULT_PIPER_HOST)): str,
            vol.Required(CONF_PIPER_PORT, default=d.get(CONF_PIPER_PORT, DEFAULT_PIPER_PORT)): int,
            vol.Required(CONF_VOICE_EN, default=d.get(CONF_VOICE_EN, DEFAULT_VOICE_EN)): str,
            vol.Required(CONF_VOICE_RU, default=d.get(CONF_VOICE_RU, DEFAULT_VOICE_RU)): str,
            vol.Required(CONF_ROBOT_ENABLED, default=d.get(CONF_ROBOT_ENABLED, True)): bool,
            vol.Required(CONF_ROBOT_FILTER, default=d.get(CONF_ROBOT_FILTER, DEFAULT_ROBOT_FILTER)): str,
        }
    )


class RobotTtsConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="Robot TTS", data={}, options=user_input)
        return self.async_show_form(step_id="user", data_schema=_schema({}))

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return RobotTtsOptionsFlow()


class RobotTtsOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        return self.async_show_form(step_id="init", data_schema=_schema(dict(self.config_entry.options)))
