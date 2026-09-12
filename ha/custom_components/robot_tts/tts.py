"""Robot TTS entity: language-aware Piper voice + ffmpeg robot filter."""

from __future__ import annotations

import asyncio
import io
import logging
import re
import wave
from typing import Any

from wyoming.audio import AudioChunk, AudioStart, AudioStop
from wyoming.client import AsyncTcpClient
from wyoming.error import Error
from wyoming.tts import Synthesize, SynthesizeVoice

from homeassistant.components.tts import (
    ATTR_VOICE,
    TextToSpeechEntity,
    TtsAudioType,
    Voice,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    CONF_PIPER_HOST,
    CONF_PIPER_PORT,
    CONF_ROBOT_ENABLED,
    CONF_ROBOT_FILTER,
    CONF_RVC_ENABLED,
    CONF_RVC_F0_METHOD,
    CONF_RVC_INDEX_RATE,
    CONF_RVC_PITCH,
    CONF_RVC_URL,
    CONF_VOICE_EN,
    CONF_VOICE_RU,
    DEFAULT_PIPER_HOST,
    DEFAULT_PIPER_PORT,
    DEFAULT_ROBOT_FILTER,
    DEFAULT_RVC_F0_METHOD,
    DEFAULT_RVC_INDEX_RATE,
    DEFAULT_RVC_PITCH,
    DEFAULT_RVC_URL,
    DEFAULT_VOICE_EN,
    DEFAULT_VOICE_RU,
)

_LOGGER = logging.getLogger(__name__)
_CYRILLIC = re.compile(r"[Ѐ-ӿ]")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([RobotTtsEntity(entry)])


class RobotTtsEntity(TextToSpeechEntity):
    # HA's TTS cache keys need a real engine name; with has_entity_name and no
    # device the name would be None ("TTS engine name is not set").
    _attr_has_entity_name = False
    _attr_name = "Robot TTS"
    _attr_supported_languages = ["en-US", "ru-RU", "en", "ru"]
    _attr_default_language = "en-US"
    _attr_supported_options = [ATTR_VOICE]

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = entry.entry_id

    # ---- options -------------------------------------------------------------
    def _opt(self, key: str, default: Any) -> Any:
        v = self._entry.options.get(key, default)
        return default if v in (None, "") else v

    @property
    def _voice_en(self) -> str:
        return self._opt(CONF_VOICE_EN, DEFAULT_VOICE_EN)

    @property
    def _voice_ru(self) -> str:
        return self._opt(CONF_VOICE_RU, DEFAULT_VOICE_RU)

    # ---- HA TTS API ----------------------------------------------------------
    @property
    def default_options(self) -> dict[str, Any]:
        return {}

    def async_get_supported_voices(self, language: str) -> list[Voice] | None:
        if language.lower().startswith("ru"):
            return [Voice(self._voice_ru, self._voice_ru)]
        return [Voice(self._voice_en, self._voice_en)]

    async def async_get_tts_audio(
        self, message: str, language: str, options: dict[str, Any]
    ) -> TtsAudioType:
        # Language comes from the TEXT, not from the pipeline: that is the point.
        is_ru = bool(_CYRILLIC.search(message))
        voice = options.get(ATTR_VOICE) or (self._voice_ru if is_ru else self._voice_en)
        _LOGGER.debug("robot_tts: lang=%s voice=%s text=%r", "ru" if is_ru else "en", voice, message)

        wav = await self._piper(message, voice)
        if self._opt(CONF_RVC_ENABLED, False):
            wav = await self._rvc(wav)
        if self._opt(CONF_ROBOT_ENABLED, True):
            wav = await self._robotize(wav, self._opt(CONF_ROBOT_FILTER, DEFAULT_ROBOT_FILTER))
        return ("wav", wav)

    # ---- RVC timbre conversion (persistent rvc_server) ----------------------
    async def _rvc(self, wav: bytes) -> bytes:
        """Send the Piper audio through the RVC service; on any failure keep the
        Piper audio so the assistant still answers."""
        from aiohttp import ClientSession, ClientTimeout

        url = self._opt(CONF_RVC_URL, DEFAULT_RVC_URL).rstrip("/") + "/convert"
        params = {
            "pitch": str(int(self._opt(CONF_RVC_PITCH, DEFAULT_RVC_PITCH))),
            "index_rate": str(float(self._opt(CONF_RVC_INDEX_RATE, DEFAULT_RVC_INDEX_RATE))),
            "f0_method": str(self._opt(CONF_RVC_F0_METHOD, DEFAULT_RVC_F0_METHOD)),
        }
        try:
            async with ClientSession(timeout=ClientTimeout(total=60)) as session:
                async with session.post(url, params=params, data=wav,
                                        headers={"Content-Type": "audio/wav"}) as resp:
                    if resp.status != 200:
                        _LOGGER.error("robot_tts: rvc_server returned %s: %s", resp.status,
                                      (await resp.text())[:200])
                        return wav
                    out = await resp.read()
                    _LOGGER.debug("robot_tts: rvc conversion took %s s",
                                  resp.headers.get("X-Convert-Seconds"))
                    return out if len(out) > 1000 else wav
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("robot_tts: rvc_server unreachable (%s), using Piper audio", err)
            return wav

    # ---- Piper over Wyoming --------------------------------------------------
    async def _piper(self, text: str, voice: str) -> bytes:
        host = self._opt(CONF_PIPER_HOST, DEFAULT_PIPER_HOST)
        port = int(self._opt(CONF_PIPER_PORT, DEFAULT_PIPER_PORT))
        try:
            async with AsyncTcpClient(host, port) as client:
                await client.write_event(
                    Synthesize(text=text, voice=SynthesizeVoice(name=voice)).event()
                )
                buf = io.BytesIO()
                wav_writer: wave.Wave_write | None = None
                while True:
                    event = await client.read_event()
                    if event is None:
                        raise HomeAssistantError("Piper closed the connection")
                    if Error.is_type(event.type):
                        err = Error.from_event(event)
                        raise HomeAssistantError(f"Piper error: {err.text} ({err.code})")
                    if AudioStart.is_type(event.type):
                        start = AudioStart.from_event(event)
                        wav_writer = wave.open(buf, "wb")
                        wav_writer.setframerate(start.rate)
                        wav_writer.setsampwidth(start.width)
                        wav_writer.setnchannels(start.channels)
                    elif AudioChunk.is_type(event.type) and wav_writer is not None:
                        wav_writer.writeframes(AudioChunk.from_event(event).audio)
                    elif AudioStop.is_type(event.type):
                        break
                if wav_writer is None:
                    raise HomeAssistantError("Piper returned no audio")
                wav_writer.close()
                return buf.getvalue()
        except OSError as err:
            raise HomeAssistantError(f"Cannot reach Piper at {host}:{port}: {err}") from err

    # ---- robot colour via ffmpeg -------------------------------------------
    @staticmethod
    async def _robotize(wav: bytes, af: str) -> bytes:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-loglevel", "error", "-i", "pipe:0", "-af", af,
            "-f", "wav", "pipe:1",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await proc.communicate(wav)
        if proc.returncode != 0 or not out:
            _LOGGER.error("robot filter failed (%s): %s", proc.returncode, err.decode(errors="replace"))
            return wav  # never fail the answer because of the effect
        return out
