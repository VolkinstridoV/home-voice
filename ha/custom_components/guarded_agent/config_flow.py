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
    CONF_BREAKER_FAILURES,
    CONF_BREAKER_SECONDS,
    CONF_DUP_SECONDS,
    CONF_FALLBACK_PHRASE,
    CONF_PRIMARY_AGENT,
    CONF_RATE_PER_DAY,
    CONF_RATE_PER_HOUR,
    CONF_RATE_PER_MINUTE,
    CONF_TIMEOUT,
    DEFAULT_BREAKER_FAILURES,
    DEFAULT_BREAKER_SECONDS,
    DEFAULT_DUP_SECONDS,
    DEFAULT_FALLBACK_PHRASE,
    DEFAULT_RATE_PER_DAY,
    DEFAULT_RATE_PER_HOUR,
    DEFAULT_RATE_PER_MINUTE,
    DEFAULT_TIMEOUT,
    DOMAIN,
)


def _schema(d: dict[str, Any]) -> vol.Schema:
    def g(key, default):
        return d.get(key, default)

    return vol.Schema(
        {
            vol.Optional(CONF_PRIMARY_AGENT, default=g(CONF_PRIMARY_AGENT, "")): str,
            vol.Optional(CONF_FALLBACK_PHRASE, default=g(CONF_FALLBACK_PHRASE, DEFAULT_FALLBACK_PHRASE)): str,
            vol.Optional(CONF_TIMEOUT, default=g(CONF_TIMEOUT, DEFAULT_TIMEOUT)): vol.All(int, vol.Range(min=5, max=120)),
            vol.Optional(CONF_RATE_PER_MINUTE, default=g(CONF_RATE_PER_MINUTE, DEFAULT_RATE_PER_MINUTE)): vol.All(int, vol.Range(min=1, max=60)),
            vol.Optional(CONF_RATE_PER_HOUR, default=g(CONF_RATE_PER_HOUR, DEFAULT_RATE_PER_HOUR)): vol.All(int, vol.Range(min=1, max=1000)),
            vol.Optional(CONF_RATE_PER_DAY, default=g(CONF_RATE_PER_DAY, DEFAULT_RATE_PER_DAY)): vol.All(int, vol.Range(min=1, max=10000)),
            vol.Optional(CONF_BREAKER_FAILURES, default=g(CONF_BREAKER_FAILURES, DEFAULT_BREAKER_FAILURES)): vol.All(int, vol.Range(min=1, max=20)),
            vol.Optional(CONF_BREAKER_SECONDS, default=g(CONF_BREAKER_SECONDS, DEFAULT_BREAKER_SECONDS)): vol.All(int, vol.Range(min=10, max=3600)),
            vol.Optional(CONF_DUP_SECONDS, default=g(CONF_DUP_SECONDS, DEFAULT_DUP_SECONDS)): vol.All(int, vol.Range(min=0, max=120)),
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
    """Let the primary agent / phrase / limits be changed later."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        return self.async_show_form(
            step_id="init", data_schema=_schema(dict(self.config_entry.options))
        )
