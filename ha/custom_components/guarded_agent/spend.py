"""Spend safety for the guarded agent: input gate, rate limits, circuit breaker.

Everything here runs *before* a request reaches the LLM, so a stuck speaker, a
garbage transcript or a dead API key cannot burn tokens. Counters survive HA
restarts through a small JSON file in the config directory.
"""

from __future__ import annotations

import json
import os
import re
import time
from collections import deque
from dataclasses import dataclass, field

STATE_FILE = "guarded_agent_spend.json"

# Spoken reasons, per language family (anything not Russian gets English).
MESSAGES = {
    "gate_empty": {
        "ru": "Я не расслышал. Повтори, пожалуйста.",
        "en": "I didn't catch that. Please say it again.",
    },
    "gate_repeat": {
        "ru": "Кажется, это был шум. Скажи ещё раз.",
        "en": "That sounded like noise. Please say it again.",
    },
    "gate_duplicate": {
        "ru": "Я уже отвечаю на это.",
        "en": "I'm already answering that.",
    },
    "limit_minute": {
        "ru": "Слишком много запросов подряд. Подожди минуту.",
        "en": "Too many requests in a row. Give me a minute.",
    },
    "limit_hour": {
        "ru": "Лимит запросов на этот час исчерпан. Попробуй позже.",
        "en": "The hourly request limit is used up. Try again later.",
    },
    "limit_day": {
        "ru": "Дневной лимит запросов исчерпан. Завтра продолжим.",
        "en": "The daily request limit is used up. We'll continue tomorrow.",
    },
    "busy": {
        "ru": "Секунду, я ещё отвечаю на предыдущий вопрос.",
        "en": "One moment, I'm still answering the previous question.",
    },
    "breaker": {
        "ru": "Связь с моим мозгом нестабильна, я сделал паузу на несколько минут.",
        "en": "My brain connection is unstable, so I'm pausing for a few minutes.",
    },
    "timeout": {
        "ru": "Ответ занял слишком много времени. Спроси ещё раз.",
        "en": "The answer took too long. Please ask again.",
    },
    "error": {
        "ru": "Не получилось получить ответ. Попробуй ещё раз через минуту.",
        "en": "I couldn't get an answer. Please try again in a minute.",
    },
}


def lang_key(language: str | None) -> str:
    return "ru" if (language or "").lower().startswith("ru") else "en"


def message(key: str, language: str | None) -> str:
    return MESSAGES[key][lang_key(language)]


_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)


def gate_reason(text: str, previous: tuple[str, float] | None, dup_seconds: float) -> str | None:
    """Return a gate key if the transcript should not go to the LLM, else None."""
    words = _WORD.findall(text.lower())
    if len(words) < 2:
        return "gate_empty"
    # a sentence (or 2–6 word chunk) repeated 3+ times back to back = STT hallucination
    n = len(words)
    for size in range(2, min(20, n // 3) + 1):
        chunk = words[:size]
        reps = 0
        while words[reps * size:(reps + 1) * size] == chunk:
            reps += 1
        if reps >= 3 and reps * size >= n * 0.8:
            return "gate_repeat"
    # too little variety in a long transcript ("hot water hot water ...")
    if n >= 12 and len(set(words)) <= max(3, n // 5):
        return "gate_repeat"
    if previous is not None:
        prev_text, prev_ts = previous
        if prev_text == text.strip().lower() and time.monotonic() - prev_ts < dup_seconds:
            return "gate_duplicate"
    return None


@dataclass
class SpendGuard:
    per_minute: int = 6
    per_hour: int = 60
    per_day: int = 400
    breaker_failures: int = 3
    breaker_seconds: int = 300
    state_path: str | None = None

    _minute: deque = field(default_factory=deque)
    _hour: deque = field(default_factory=deque)
    _day_count: int = 0
    _day: str = ""
    _failures: int = 0
    _open_until: float = 0.0
    _busy: bool = False
    _last_text: tuple[str, float] | None = None

    # ---- persistence ----------------------------------------------------------
    def load(self) -> None:
        if not self.state_path or not os.path.exists(self.state_path):
            return
        try:
            with open(self.state_path, encoding="utf-8") as f:
                d = json.load(f)
            if d.get("day") == time.strftime("%Y-%m-%d"):
                self._day = d["day"]
                self._day_count = int(d.get("day_count", 0))
        except (OSError, ValueError):
            pass

    def save(self) -> None:
        if not self.state_path:
            return
        try:
            with open(self.state_path, "w", encoding="utf-8") as f:
                json.dump({"day": self._day, "day_count": self._day_count}, f)
        except OSError:
            pass

    # ---- checks ---------------------------------------------------------------
    def _roll_day(self) -> None:
        today = time.strftime("%Y-%m-%d")
        if self._day != today:
            self._day, self._day_count = today, 0

    def limit_reason(self) -> str | None:
        now = time.monotonic()
        while self._minute and now - self._minute[0] > 60:
            self._minute.popleft()
        while self._hour and now - self._hour[0] > 3600:
            self._hour.popleft()
        self._roll_day()
        if len(self._minute) >= self.per_minute:
            return "limit_minute"
        if len(self._hour) >= self.per_hour:
            return "limit_hour"
        if self._day_count >= self.per_day:
            return "limit_day"
        return None

    def breaker_open(self) -> bool:
        return time.monotonic() < self._open_until

    def gate(self, text: str, dup_seconds: float) -> str | None:
        reason = gate_reason(text, self._last_text, dup_seconds)
        self._last_text = (text.strip().lower(), time.monotonic())
        return reason

    def acquire(self) -> bool:
        if self._busy:
            return False
        self._busy = True
        return True

    def release(self) -> None:
        self._busy = False

    def record_request(self) -> None:
        now = time.monotonic()
        self._minute.append(now)
        self._hour.append(now)
        self._roll_day()
        self._day_count += 1
        # persisted by the caller via save(), off the event loop

    def record_success(self) -> None:
        self._failures = 0

    def record_failure(self) -> bool:
        """Return True if the breaker just opened."""
        self._failures += 1
        if self._failures >= self.breaker_failures:
            self._open_until = time.monotonic() + self.breaker_seconds
            self._failures = 0
            return True
        return False

    def snapshot(self) -> dict:
        self._roll_day()
        return {
            "minute": len(self._minute),
            "hour": len(self._hour),
            "day": self._day_count,
            "breaker_open": self.breaker_open(),
        }
