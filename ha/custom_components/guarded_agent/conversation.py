"""Conversation entity that guards a primary (LLM) agent.

Order of checks for every transcript:
  1. input gate      – empty / repetitive / duplicate transcripts never reach the LLM
  2. rate limits     – per minute / hour / day
  3. circuit breaker – after N consecutive failures the LLM is not called for a while
  4. concurrency     – one LLM call at a time
  5. the primary agent, with a timeout
Every refusal or failure is answered with a *spoken* sentence in the user's
language, and every turn is appended to nabu_conversations.jsonl.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime

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
)
from .spend import STATE_FILE, SpendGuard, message

_LOGGER = logging.getLogger(__name__)

CONVERSATION_LOG = "nabu_conversations.jsonl"  # inside the HA config directory


def _append_log(hass: HomeAssistant, record: dict) -> None:
    """Persist one exchange as a JSON line (HA keeps only the last 10 runs in memory)."""
    record["ts"] = datetime.now().isoformat(timespec="seconds")
    try:
        with open(hass.config.path(CONVERSATION_LOG), "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as err:
        _LOGGER.warning("Guarded Agent: cannot write conversation log: %s", err)


def _tool_calls_of_last_turn(chat_log: ChatLog) -> list[dict]:
    """Tool calls made by the assistant in the most recent turn (web_search etc.)."""
    calls: list[dict] = []
    for item in reversed(chat_log.content):
        role = getattr(item, "role", None)
        if role == "user":
            break
        if role == "assistant":
            for tc in getattr(item, "tool_calls", None) or []:
                calls.append({"tool": getattr(tc, "tool_name", "?"),
                              "args": getattr(tc, "tool_args", None)})
    calls.reverse()
    return calls


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the guarded conversation entity."""
    async_add_entities([GuardedAgentEntity(hass, entry)])


class GuardedAgentEntity(ConversationEntity):
    """Forward to the primary agent; speak a fixed phrase if it fails."""

    _attr_has_entity_name = True
    _attr_name = None
    # The wrapped LLM agent streams its deltas into the same chat log (same
    # conversation id), so the pipeline can start TTS before the answer ends.
    _attr_supports_streaming = True

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = entry.entry_id
        self._guard = SpendGuard(
            per_minute=int(self._opt_of(entry, CONF_RATE_PER_MINUTE, DEFAULT_RATE_PER_MINUTE)),
            per_hour=int(self._opt_of(entry, CONF_RATE_PER_HOUR, DEFAULT_RATE_PER_HOUR)),
            per_day=int(self._opt_of(entry, CONF_RATE_PER_DAY, DEFAULT_RATE_PER_DAY)),
            breaker_failures=int(self._opt_of(entry, CONF_BREAKER_FAILURES, DEFAULT_BREAKER_FAILURES)),
            breaker_seconds=int(self._opt_of(entry, CONF_BREAKER_SECONDS, DEFAULT_BREAKER_SECONDS)),
            state_path=hass.config.path(STATE_FILE),
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        await self.hass.async_add_executor_job(self._guard.load)

    @staticmethod
    def _opt_of(entry: ConfigEntry, key: str, default):
        value = entry.options.get(key, default)
        return value if value not in (None, "") else default

    def _opt(self, key: str, default):
        return self._opt_of(self._entry, key, default)

    @property
    def supported_languages(self) -> list[str] | str:
        return MATCH_ALL

    # ---- helpers ----------------------------------------------------------------
    def _spoken(self, user_input: ConversationInput, chat_log: ChatLog, text: str,
                reason: str, extra: dict | None = None) -> ConversationResult:
        response = intent.IntentResponse(language=user_input.language)
        response.async_set_speech(text)
        chat_log.async_add_assistant_content_without_tools(
            AssistantContent(agent_id=user_input.agent_id, content=text)
        )
        rec = {
            "language": user_input.language,
            "conversation_id": user_input.conversation_id,
            "user": user_input.text,
            "agent": reason,
            "answer": text,
            "guard": self._guard.snapshot(),
        }
        if extra:
            rec.update(extra)
        self.hass.async_add_executor_job(_append_log, self.hass, rec)
        return ConversationResult(
            conversation_id=user_input.conversation_id,
            response=response,
            continue_conversation=False,
        )

    # ---- main -------------------------------------------------------------------
    async def _async_handle_message(
        self, user_input: ConversationInput, chat_log: ChatLog
    ) -> ConversationResult:
        primary: str = self._option(CONF_PRIMARY_AGENT, "")
        phrase: str = self._option(CONF_FALLBACK_PHRASE, DEFAULT_FALLBACK_PHRASE)
        timeout: int = int(self._option(CONF_TIMEOUT, DEFAULT_TIMEOUT))
        dup_seconds = float(self._option(CONF_DUP_SECONDS, DEFAULT_DUP_SECONDS))
        lang = user_input.language

        # 1. input gate (never spends a token)
        gate = self._guard.gate(user_input.text, dup_seconds)
        if gate:
            _LOGGER.info("Guarded Agent: gate %s for %r", gate, user_input.text)
            return self._spoken(user_input, chat_log, message(gate, lang), gate)

        # 2. rate limits
        limit = self._guard.limit_reason()
        if limit:
            _LOGGER.warning("Guarded Agent: %s (%s)", limit, self._guard.snapshot())
            return self._spoken(user_input, chat_log, message(limit, lang), limit)

        # 3. circuit breaker
        if self._guard.breaker_open():
            _LOGGER.warning("Guarded Agent: breaker open, not calling %s", primary)
            return self._spoken(user_input, chat_log, message("breaker", lang), "breaker")

        # no primary configured -> the fixed fallback phrase (English by design)
        if not primary or primary == self.entity_id or self.hass.states.get(primary) is None:
            _LOGGER.warning("Guarded Agent: primary agent %r not available, using fallback", primary)
            return self._spoken(user_input, chat_log, phrase, "fallback")

        # 4. one LLM call at a time
        if not self._guard.acquire():
            return self._spoken(user_input, chat_log, message("busy", lang), "busy")
        t0 = time.monotonic()
        try:
            self._guard.record_request()
            self.hass.async_add_executor_job(self._guard.save)
            result = await asyncio.wait_for(
                async_converse(
                    self.hass,
                    text=user_input.text,
                    conversation_id=user_input.conversation_id,
                    context=user_input.context,
                    language=lang,
                    agent_id=primary,
                    device_id=user_input.device_id,
                    satellite_id=user_input.satellite_id,
                ),
                timeout=timeout,
            )
            if result.response.error_code is None:
                self._guard.record_success()
                answer = result.response.speech.get("plain", {}).get("speech", "")
                self.hass.async_add_executor_job(_append_log, self.hass, {
                    "language": lang,
                    "conversation_id": user_input.conversation_id,
                    "user": user_input.text,
                    "agent": primary,
                    "answer": answer,
                    "llm_seconds": round(time.monotonic() - t0, 2),
                    "tool_calls": _tool_calls_of_last_turn(chat_log),
                    "est_tokens": (len(user_input.text) + len(answer)) // 4 + 150,
                    "guard": self._guard.snapshot(),
                    "continue": result.continue_conversation,
                })
                return result
            _LOGGER.warning("Guarded Agent: %s returned error %s: %s", primary,
                            result.response.error_code, result.response.speech)
            opened = self._guard.record_failure()
            return self._spoken(user_input, chat_log, message("error", lang), "agent_error",
                                {"error": str(result.response.error_code), "breaker_opened": opened})
        except TimeoutError:
            _LOGGER.warning("Guarded Agent: %s timed out after %ss", primary, timeout)
            opened = self._guard.record_failure()
            return self._spoken(user_input, chat_log, message("timeout", lang), "timeout",
                                {"breaker_opened": opened})
        except Exception as err:  # noqa: BLE001 - any failure means a spoken error
            _LOGGER.exception("Guarded Agent: %s raised", primary)
            opened = self._guard.record_failure()
            return self._spoken(user_input, chat_log, message("error", lang), "exception",
                                {"error": f"{type(err).__name__}: {err}"[:200], "breaker_opened": opened})
        finally:
            self._guard.release()

    def _option(self, key: str, default):
        return self._opt(key, default)
