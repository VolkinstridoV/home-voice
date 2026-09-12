#!/usr/bin/env python3
"""Run tests/phrases.yaml through the real pipeline and grade the text answers.

Usage: HA_HOST=192.168.0.100 tools/run_tests.py [tests/phrases.yaml] [--only substring]
Paces itself to stay under the guarded agent's per-minute limit.
Prints a pass/fail table and writes tests/last_run.json.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time

import yaml

sys.path.insert(0, os.path.dirname(__file__))
from ha_pipeline_test import run_once  # noqa: E402

CYR = re.compile(r"[Ѐ-ӿ]")
LAT = re.compile(r"[A-Za-z]")
MD = re.compile(r"(^|\n)\s*([-*•]|\d+\.)\s|\*\*|#{1,6}\s")
SENT = re.compile(r"[.!?…]+(\s|$)")


def answer_lang(text: str) -> str:
    c, l = len(CYR.findall(text)), len(LAT.findall(text))
    return "ru" if c > l else "en"


def sentences(text: str) -> int:
    return max(1, len(SENT.findall(text.strip()))) if text.strip() else 0


def grade(case: dict, res: dict, journal_agent: str | None) -> list[str]:
    exp = case.get("expect", {})
    fails: list[str] = []
    ans = (res.get("response") or "")
    if res.get("error"):
        return [f"pipeline error: {res['error'][:120]}"]
    if "gate" in exp:
        ok = (journal_agent or "").startswith("gate_") if exp["gate"] == "any" else journal_agent == exp["gate"]
        if not ok:
            fails.append(f"expected gate {exp['gate']}, journal agent={journal_agent}")
        return fails
    if not ans:
        return ["empty answer"]
    if "lang" in exp and answer_lang(ans) != exp["lang"]:
        fails.append(f"answer language {answer_lang(ans)} != {exp['lang']}")
    if "contains" in exp and not any(s.lower() in ans.lower() for s in exp["contains"]):
        fails.append(f"none of {exp['contains']} in answer")
    if "not_contains" in exp and any(s.lower() in ans.lower() for s in exp["not_contains"]):
        fails.append(f"forbidden substring in answer")
    if "max_sentences" in exp and sentences(ans) > exp["max_sentences"]:
        fails.append(f"{sentences(ans)} sentences > {exp['max_sentences']}")
    if exp.get("no_markdown") and MD.search(ans):
        fails.append("markdown/list formatting in answer")
    budget = exp.get("max_intent_s", case.get("_max_intent_s", 12))
    llm_s = (res.get("intent_s") or 0) - (res.get("stt_s") or 0)
    if llm_s > budget:
        fails.append(f"LLM {llm_s:.1f}s > {budget}s")
    return fails


def last_journal_agent(host: str) -> str | None:
    """Ask the server for the agent field of the last journal line (via ssh)."""
    import subprocess
    try:
        out = subprocess.run(
            ["ssh", "-o", "ControlMaster=no", "-o", "ControlPath=none", "server",
             "sudo tail -1 /opt/homeassistant/config/nabu_conversations.jsonl"],
            capture_output=True, text=True, timeout=30).stdout.strip()
        return json.loads(out).get("agent") if out else None
    except Exception:  # noqa: BLE001
        return None


async def main() -> int:
    path = "tests/phrases.yaml"
    only = None
    args = sys.argv[1:]
    if args and not args[0].startswith("--"):
        path = args.pop(0)
    if "--only" in args:
        only = args[args.index("--only") + 1]
    spec = yaml.safe_load(open(path, encoding="utf-8"))
    d = spec["defaults"]
    cases = [c for c in spec["cases"] if not only or only.lower() in c["say"].lower()]
    results = []
    t_suite = time.time()
    print(f"{len(cases)} cases, pacing ~11 s each\n")
    for i, case in enumerate(cases, 1):
        t0 = time.time()
        lang = case["lang"]
        voice = d["voice_ru"] if lang == "ru" else d["voice_en"]
        tts_lang = "ru_RU" if lang == "ru" else "en_US"
        case["_max_intent_s"] = d.get("max_intent_s", 12)
        res = await run_once(d["pipeline_id"], tts_lang, "tts.piper", voice, case["say"])
        agent = last_journal_agent(os.environ.get("HA_HOST", "")) if "gate" in case.get("expect", {}) else None
        fails = grade(case, res, agent)
        status = "PASS" if not fails else "FAIL"
        llm = (res.get("intent_s") or 0) - (res.get("stt_s") or 0)
        print(f"{i:2d} {status} [{lang}] {case['say'][:52]!r:56} stt={res.get('stt_s', 0):.1f}s llm={llm:.1f}s")
        if fails:
            print(f"      answer: {(res.get('response') or '')[:160]!r}")
            for f in fails:
                print(f"      - {f}")
        results.append({"case": case["say"], "lang": lang, "status": status, "fails": fails,
                        "transcript": res.get("transcript"), "response": res.get("response"),
                        "stt_s": res.get("stt_s"), "llm_s": round(llm, 2)})
        # stay under 6 requests / minute
        await asyncio.sleep(max(0, 11 - (time.time() - t0)))
    passed = sum(r["status"] == "PASS" for r in results)
    print(f"\n{passed}/{len(results)} passed in {time.time() - t_suite:.0f}s")
    os.makedirs("tests", exist_ok=True)
    with open("tests/last_run.json", "w", encoding="utf-8") as f:
        json.dump({"ts": time.strftime("%Y-%m-%d %H:%M"), "passed": passed, "total": len(results),
                   "results": results}, f, ensure_ascii=False, indent=1)
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
