"""Config and options flow for Guarded Agent."""

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
    CONF_FALLBACK_PHRASE,
    CONF_PRIMARY_AGENT,
    CONF_TIMEOUT,
    DEFAULT_FALLBACK_PHRASE,
    DEFAULT_TIMEOUT,
    DOMAIN,
)


def _schema(defaults: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Optional(
                CONF_PRIMARY_AGENT, default=defaults.get(CONF_PRIMARY_AGENT, "")
            ): str,
            vol.Optional(
                CONF_FALLBACK_PHRASE,
                default=defaults.get(CONF_FALLBACK_PHRASE, DEFAULT_FALLBACK_PHRASE),
            ): str,
            vol.Optional(
                CONF_TIMEOUT, default=defaults.get(CONF_TIMEOUT, DEFAULT_TIMEOUT)
            ): vol.All(int, vol.Range(min=5, max=120)),
        }
    )


class GuardedAgentConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial setup."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                title="Guarded Agent", data={}, options=user_input
            )
        return self.async_show_form(step_id="user", data_schema=_schema({}))

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return GuardedAgentOptionsFlow()


class GuardedAgentOptionsFlow(OptionsFlow):
    """Let the primary agent / phrase / timeout be changed later."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        return self.async_show_form(
            step_id="init", data_schema=_schema(dict(self.config_entry.options))
        )
