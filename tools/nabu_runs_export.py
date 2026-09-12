#!/usr/bin/env python3
"""Export Assist pipeline runs (stage timings) before Home Assistant forgets them.

HA keeps only the last 10 debug runs per pipeline in memory. Run this every few
minutes (cron) to append new runs as JSON lines: wake -> vad -> stt-end ->
intent-end -> tts, with transcript and answer. Together with
nabu_conversations.jsonl (written by guarded_agent) any turn can be reconstructed.

Usage: HA_HOST=127.0.0.1 HA_TOKEN_FILE=/path/token nabu_runs_export.py <pipeline_id> <out.jsonl>
"""
import asyncio
import json
import os
import sys

import websockets

HA_HOST = os.environ.get("HA_HOST", "127.0.0.1")
HA_WS = f"ws://{HA_HOST}:8123/api/websocket"
TOKEN_FILE = os.environ.get("HA_TOKEN_FILE", os.path.expanduser("~/.config/homeassistant/token"))


async def ws_call(ws, msg_id: int, payload: dict) -> dict:
    payload["id"] = msg_id
    await ws.send(json.dumps(payload))
    while True:
        msg = json.loads(await ws.recv())
        if msg.get("id") == msg_id and msg.get("type") == "result":
            return msg


def summarize(run_id: str, events: list[dict]) -> dict:
    t0 = None
    rec = {"run_id": run_id, "stages": {}, "transcript": None, "answer": None, "error": None}
    for ev in events:
        ts = ev.get("timestamp")
        et = ev.get("type")
        data = ev.get("data") or {}
        if t0 is None:
            t0 = ts
            rec["ts"] = ts
        rec["stages"][et] = ts
        if et == "stt-end":
            rec["transcript"] = data.get("stt_output", {}).get("text")
        elif et == "intent-end":
            rec["answer"] = data.get("intent_output", {}).get("response", {}).get("speech", {}).get("plain", {}).get("speech")
        elif et == "error":
            rec["error"] = data
    # durations in seconds between key stages
    from datetime import datetime

    def t(name):
        v = rec["stages"].get(name)
        return datetime.fromisoformat(v) if v else None

    def dur(a, b):
        ta, tb = t(a), t(b)
        return round((tb - ta).total_seconds(), 2) if ta and tb else None

    rec["timing"] = {
        "speech_s": dur("stt-vad-start", "stt-vad-end"),
        "stt_s": dur("stt-vad-end", "stt-end"),
        "llm_s": dur("intent-start", "intent-end"),
        "total_s": dur("run-start", "run-end"),
        "aborted": rec["transcript"] is None and "run-end" in rec["stages"],
    }
    return rec


async def main() -> int:
    pipeline_id, out_path = sys.argv[1], sys.argv[2]
    token = open(TOKEN_FILE).read().strip()
    seen = set()
    if os.path.exists(out_path):
        with open(out_path, encoding="utf-8") as f:
            for line in f:
                try:
                    seen.add(json.loads(line)["run_id"])
                except (ValueError, KeyError):
                    pass
    async with websockets.connect(HA_WS, max_size=50 * 1024 * 1024) as ws:
        json.loads(await ws.recv())
        await ws.send(json.dumps({"type": "auth", "access_token": token}))
        if json.loads(await ws.recv())["type"] != "auth_ok":
            print("auth failed"); return 1
        lst = await ws_call(ws, 1, {"type": "assist_pipeline/pipeline_debug/list", "pipeline_id": pipeline_id})
        runs = lst.get("result", {}).get("pipeline_runs", [])
        new = 0
        i = 2
        with open(out_path, "a", encoding="utf-8") as f:
            for r in runs:
                rid = r["pipeline_run_id"]
                if rid in seen:
                    continue
                det = await ws_call(ws, i, {"type": "assist_pipeline/pipeline_debug/get",
                                            "pipeline_id": pipeline_id, "pipeline_run_id": rid})
                i += 1
                events = det.get("result", {}).get("events") or []
                if not events or "run-end" not in {e.get("type") for e in events}:
                    continue  # still running; pick it up next time
                f.write(json.dumps(summarize(rid, events), ensure_ascii=False) + "\n")
                new += 1
        print(f"exported {new} new runs ({len(runs)} in HA memory)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
