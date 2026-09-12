"""Conversation entity that guards a primary (LLM) agent with a fixed fallback."""

from __future__ import annotations

import asyncio
import logging

from homeassistant.components.conversation import (
    AssistantContent,
    ChatLog,
    ConversationEntity,
    ConversationInput,
    ConversationResult,
    async_converse,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import MATCH_ALL
from homeassistant.core import HomeAssistant
from homeassistant.helpers import intent
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    CONF_FALLBACK_PHRASE,
    CONF_PRIMARY_AGENT,
    CONF_TIMEOUT,
    DEFAULT_FALLBACK_PHRASE,
    DEFAULT_TIMEOUT,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the guarded conversation entity."""
    async_add_entities([GuardedAgentEntity(entry)])


class GuardedAgentEntity(ConversationEntity):
    """Forward to the primary agent; speak a fixed phrase if it fails."""

    _attr_has_entity_name = True
    _attr_name = None

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = entry.entry_id

    @property
    def supported_languages(self) -> list[str] | str:
        return MATCH_ALL

    def _option(self, key: str, default):
        value = self._entry.options.get(key, default)
        return value if value not in (None, "") else default

    async def _async_handle_message(
        self, user_input: ConversationInput, chat_log: ChatLog
    ) -> ConversationResult:
        primary: str = self._option(CONF_PRIMARY_AGENT, "")
        phrase: str = self._option(CONF_FALLBACK_PHRASE, DEFAULT_FALLBACK_PHRASE)
        timeout: int = int(self._option(CONF_TIMEOUT, DEFAULT_TIMEOUT))

        if primary and primary != self.entity_id:
            if self.hass.states.get(primary) is None:
                _LOGGER.warning(
                    "Guarded Agent: primary agent %s does not exist, using fallback",
                    primary,
                )
            else:
                try:
                    result = await asyncio.wait_for(
                        async_converse(
                            self.hass,
                            text=user_input.text,
                            conversation_id=user_input.conversation_id,
                            context=user_input.context,
                            language=user_input.language,
                            agent_id=primary,
                            device_id=user_input.device_id,
                            satellite_id=user_input.satellite_id,
                        ),
                        timeout=timeout,
                    )
                    if result.response.error_code is None:
                        return result
                    _LOGGER.warning(
                        "Guarded Agent: primary agent %s returned error %s: %s",
                        primary,
                        result.response.error_code,
                        result.response.speech,
                    )
                except TimeoutError:
                    _LOGGER.warning(
                        "Guarded Agent: primary agent %s timed out after %ss",
                        primary,
                        timeout,
                    )
                except Exception:  # noqa: BLE001 - any failure means fallback
                    _LOGGER.exception(
                        "Guarded Agent: primary agent %s raised, using fallback", primary
                    )
        else:
            _LOGGER.info("Guarded Agent: no primary agent configured, using fallback")

        response = intent.IntentResponse(language=user_input.language)
        response.async_set_speech(phrase)
        chat_log.async_add_assistant_content_without_tools(
            AssistantContent(agent_id=user_input.agent_id, content=phrase)
        )
        return ConversationResult(
            conversation_id=user_input.conversation_id,
            response=response,
            continue_conversation=False,
        )
