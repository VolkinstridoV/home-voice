"""Offline checks for the guarded agent's spend guard (no Home Assistant needed).

Run: python tests/test_spend.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "ha", "custom_components", "guarded_agent"))

from spend import SpendGuard, gate_reason, message  # noqa: E402

GATE_CASES = {
    "": "gate_empty",
    "hi": "gate_empty",
    "what is the capital of france": None,
    "I'm going to make a lot of hot water. I'm going to make a lot of hot water. "
    "I'm going to make a lot of hot water.": "gate_repeat",
    "Пошел нахуй": None,
    "Какая столица Франции?": None,
    "да да да да да да да да да да да да": "gate_repeat",
    "Переведи на английский: где здесь ближайшая аптека?": None,
}


def main() -> int:
    failed = 0
    for text, expected in GATE_CASES.items():
        got = gate_reason(text, None, 10)
        ok = got == expected
        failed += not ok
        print(("OK  " if ok else "FAIL"), repr(text[:48]), "->", got)

    g = SpendGuard(per_minute=3, per_hour=100, per_day=1000)
    seq = []
    for _ in range(5):
        r = g.limit_reason()
        seq.append(r or "allowed")
        if not r:
            g.record_request()
    ok = seq == ["allowed", "allowed", "allowed", "limit_minute", "limit_minute"]
    failed += not ok
    print(("OK  " if ok else "FAIL"), "rate limiter:", seq)

    g2 = SpendGuard(breaker_failures=2, breaker_seconds=60)
    opened = [g2.record_failure(), g2.record_failure()]
    ok = opened == [False, True] and g2.breaker_open()
    failed += not ok
    print(("OK  " if ok else "FAIL"), "breaker:", opened, g2.breaker_open())

    dup = gate_reason("hello there", ("hello there", __import__("time").monotonic()), 10)
    ok = dup == "gate_duplicate"
    failed += not ok
    print(("OK  " if ok else "FAIL"), "duplicate:", dup)

    print(message("limit_minute", "ru"), "|", message("busy", "en-US"))
    print("FAILED" if failed else "ALL OK", failed)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
