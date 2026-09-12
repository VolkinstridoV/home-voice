"""Fact storage: a small JSON file in the Home Assistant config directory."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime

from .const import MAX_FACTS


@dataclass
class Fact:
    id: int
    text: str
    category: str = "other"
    ts: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    source: str = ""  # conversation/device id if known


class MemoryStore:
    def __init__(self, path: str) -> None:
        self.path = path
        self.facts: list[Fact] = []
        self._next_id = 1

    # ---- sync I/O, call through hass.async_add_executor_job ------------------
    def load(self) -> None:
        if not os.path.exists(self.path):
            return
        with open(self.path, encoding="utf-8") as f:
            data = json.load(f)
        self.facts = [Fact(**d) for d in data.get("facts", [])]
        self._next_id = max([f.id for f in self.facts], default=0) + 1

    def save(self) -> None:
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"facts": [asdict(x) for x in self.facts]}, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)

    # ---- operations ----------------------------------------------------------
    def remember(self, text: str, category: str, source: str = "") -> Fact:
        text = " ".join(text.split())
        for existing in self.facts:
            if existing.text.lower() == text.lower():
                return existing
        if len(self.facts) >= MAX_FACTS:
            self.facts.pop(0)
        fact = Fact(id=self._next_id, text=text, category=category, source=source)
        self._next_id += 1
        self.facts.append(fact)
        return fact

    def forget(self, needle: str) -> list[Fact]:
        """Remove facts by id or by substring; returns what was removed."""
        needle = needle.strip().lower()
        removed = []
        keep = []
        for f in self.facts:
            if (needle.isdigit() and f.id == int(needle)) or (not needle.isdigit() and needle in f.text.lower()):
                removed.append(f)
            else:
                keep.append(f)
        self.facts = keep
        return removed

    def render(self) -> str:
        if not self.facts:
            return "(nothing remembered yet)"
        lines = []
        for f in self.facts:
            lines.append(f"- [{f.id}] ({f.category}) {f.text}")
        return "\n".join(lines)
