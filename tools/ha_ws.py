"""Send one command to the Home Assistant WebSocket API and print the JSON result.

Usage: ha_ws.py '<json command without id>'
Example: ha_ws.py '{"type": "config_entries/flow/progress"}'
Token is read from ~/.config/homeassistant/token.
"""
import asyncio
import json
import os
import sys

import websockets

HA_HOST = os.environ.get("HA_HOST", "homeassistant.local")
HA_WS = f"ws://{HA_HOST}:8123/api/websocket"


async def main() -> int:
    cmd = json.loads(sys.argv[1])
    token = open(os.path.expanduser("~/.config/homeassistant/token")).read().strip()
    async with websockets.connect(HA_WS, max_size=20 * 1024 * 1024) as ws:
        hello = json.loads(await ws.recv())
        assert hello["type"] == "auth_required", hello
        await ws.send(json.dumps({"type": "auth", "access_token": token}))
        auth = json.loads(await ws.recv())
        if auth["type"] != "auth_ok":
            print("auth failed:", auth)
            return 1
        cmd["id"] = 1
        await ws.send(json.dumps(cmd))
        while True:
            msg = json.loads(await ws.recv())
            if msg.get("id") == 1 and msg.get("type") == "result":
                print(json.dumps(msg, ensure_ascii=False, indent=1))
                return 0 if msg.get("success") else 2
            if msg.get("id") == 1 and msg.get("type") == "event":
                print(json.dumps(msg, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
