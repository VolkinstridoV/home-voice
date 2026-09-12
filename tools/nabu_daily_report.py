#!/usr/bin/env python3
"""One-line-per-day report from the two journals.

Reads nabu_conversations.jsonl (guarded_agent: text, agent, llm_seconds, tool
calls, guard counters) and nabu_runs.jsonl (pipeline stage timings) and prints
per day: requests, by outcome, LLM/STT latency (p50/p90), searches, estimated
cost, aborted runs.

Usage: nabu_daily_report.py <conversations.jsonl> <runs.jsonl> [--days N]
Estimated cost uses Sonnet 5 list prices ($2 in / $10 out per 1M tokens) and the
rough per-turn token estimate written by guarded_agent (est_tokens ≈ text/4 + 150).
"""
import json
import sys
from collections import defaultdict


def pct(values, p):
    if not values:
        return None
    v = sorted(values)
    return round(v[min(len(v) - 1, int(len(v) * p))], 1)


def main() -> int:
    conv_path, runs_path = sys.argv[1], sys.argv[2]
    days = int(sys.argv[sys.argv.index("--days") + 1]) if "--days" in sys.argv else 7
    by_day = defaultdict(lambda: {"turns": 0, "outcomes": defaultdict(int), "llm": [], "stt": [],
                                  "searches": 0, "est_tokens": 0, "aborted": 0})
    try:
        for line in open(conv_path, encoding="utf-8"):
            r = json.loads(line)
            d = by_day[r["ts"][:10]]
            d["turns"] += 1
            a = r.get("agent", "?")
            d["outcomes"]["llm" if a.startswith("conversation.") else a] += 1
            if "llm_seconds" in r:
                d["llm"].append(r["llm_seconds"])
            d["searches"] += sum(1 for t in r.get("tool_calls", []) if t.get("tool") == "web_search")
            d["est_tokens"] += r.get("est_tokens", 0)
    except FileNotFoundError:
        pass
    try:
        for line in open(runs_path, encoding="utf-8"):
            r = json.loads(line)
            d = by_day[r["ts"][:10]]
            t = r.get("timing", {})
            if t.get("stt_s") is not None:
                d["stt"].append(t["stt_s"])
            if t.get("aborted"):
                d["aborted"] += 1
    except FileNotFoundError:
        pass
    for day in sorted(by_day)[-days:]:
        d = by_day[day]
        # est cost: assume ~2500 input tokens/turn (cached prompt ~ 40% cheaper not modelled) + est output
        usd = d["outcomes"]["llm"] * 2500 / 1e6 * 2.0 + d["est_tokens"] / 1e6 * 10.0
        out = ", ".join(f"{k}={v}" for k, v in sorted(d["outcomes"].items()))
        print(f"{day}  turns={d['turns']:3d}  [{out}]  llm p50/p90={pct(d['llm'], .5)}/{pct(d['llm'], .9)}s"
              f"  stt p50/p90={pct(d['stt'], .5)}/{pct(d['stt'], .9)}s  searches={d['searches']}"
              f"  aborted_runs={d['aborted']}  est≈${usd:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
