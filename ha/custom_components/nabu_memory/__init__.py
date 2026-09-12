"""Nabu Memory: durable facts about the household, exposed to LLM agents.

Registers an LLM API ("nabu_memory") with two tools, `remember` and `forget`,
and injects the current facts into the agent's system prompt through the API
prompt. Select it in the conversation agent's "Control Home Assistant" /
LLM API list next to Assist.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import llm
from homeassistant.util.json import JsonObjectType

from .const import API_ID, API_NAME, CATEGORIES, DOMAIN, MEMORY_FILE
from .memory import MemoryStore

_LOGGER = logging.getLogger(__name__)

API_PROMPT = """You have a long-term memory about this household. Facts you know:
{facts}

Rules for memory:
- When someone tells you a durable fact about a person, the home, a preference or a routine (for example "mom listens to Yandex Music", "Ken watches Netflix on the living-room TV", "Arthur studies Python in the morning"), call `remember` with one short sentence in English. Confirm aloud, briefly, in the speaker's language.
- When asked to forget something, call `forget`.
- Never store transient things (today's weather, a one-off question), secrets, passwords or card numbers.
- Use the facts to personalise answers; do not recite the list unless asked what you remember."""


class RememberTool(llm.Tool):
    name = "remember"
    description = ("Store one durable fact about a person, the home, a preference or a routine. "
                   "Use a short sentence in English.")
    parameters = vol.Schema({
        vol.Required("fact"): str,
        vol.Optional("category", default="other"): vol.In(CATEGORIES),
    })

    def __init__(self, store: MemoryStore) -> None:
        self._store = store

    async def async_call(self, hass: HomeAssistant, tool_input: llm.ToolInput,
                         llm_context: llm.LLMContext) -> JsonObjectType:
        fact = self._store.remember(tool_input.tool_args["fact"],
                                    tool_input.tool_args.get("category", "other"),
                                    source=llm_context.device_id or "")
        await hass.async_add_executor_job(self._store.save)
        _LOGGER.info("nabu_memory: remembered [%s] %s", fact.id, fact.text)
        return {"stored": True, "id": fact.id, "fact": fact.text, "total": len(self._store.facts)}


class ForgetTool(llm.Tool):
    name = "forget"
    description = "Remove remembered facts by id or by a phrase they contain."
    parameters = vol.Schema({vol.Required("fact_id_or_text"): str})

    def __init__(self, store: MemoryStore) -> None:
        self._store = store

    async def async_call(self, hass: HomeAssistant, tool_input: llm.ToolInput,
                         llm_context: llm.LLMContext) -> JsonObjectType:
        removed = self._store.forget(tool_input.tool_args["fact_id_or_text"])
        await hass.async_add_executor_job(self._store.save)
        _LOGGER.info("nabu_memory: forgot %s", [f.text for f in removed])
        return {"removed": [f.text for f in removed], "total": len(self._store.facts)}


class NabuMemoryAPI(llm.API):
    """The LLM API instance that carries the facts and the two tools."""

    def __init__(self, hass: HomeAssistant, store: MemoryStore) -> None:
        super().__init__(hass=hass, id=API_ID, name=API_NAME)
        self._store = store

    async def async_get_api_instance(self, llm_context: llm.LLMContext) -> llm.APIInstance:
        return llm.APIInstance(
            api=self,
            api_prompt=API_PROMPT.format(facts=self._store.render()),
            llm_context=llm_context,
            tools=[RememberTool(self._store), ForgetTool(self._store)],
        )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    store = MemoryStore(hass.config.path(MEMORY_FILE))
    await hass.async_add_executor_job(store.load)
    api = NabuMemoryAPI(hass, store)
    unregister = llm.async_register_api(hass, api)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {"store": store, "unregister": unregister}
    _LOGGER.info("nabu_memory: API registered with %d facts", len(store.facts))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    data: dict[str, Any] = hass.data.get(DOMAIN, {}).pop(entry.entry_id, {})
    if data.get("unregister"):
        data["unregister"]()
    return True
