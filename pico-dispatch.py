#!/usr/bin/env python3
"""
Dispatch a task via pico protocol WebSocket.
Usage: pico-dispatch.py "task message"
Returns the response text.
"""

import sys
import json
import asyncio
import aiohttp
import os

_cfg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
with open(_cfg_path) as _f:
    _cfg = json.load(_f)

LAUNCHER_URL = "http://localhost:18800"
DASHBOARD_TOKEN = _cfg["pico"]["dashboard_token"]
PICO_TOKEN = _cfg["pico"]["pico_token"]


async def dispatch(message):
    # Get auth cookie
    async with aiohttp.ClientSession() as s:
        async with s.get(
            f"{LAUNCHER_URL}/?token={DASHBOARD_TOKEN}",
            allow_redirects=False
        ) as r:
            cookie = r.cookies.get("picoclaw_launcher_auth")
            if not cookie:
                print("[auth failed]")
                return

    # Connect and send
    cookies = {"picoclaw_launcher_auth": cookie.value}
    async with aiohttp.ClientSession(cookies=cookies) as s:
        try:
            async with s.ws_connect(
                f"ws://localhost:18800/pico/ws",
                protocols=[f"token.{PICO_TOKEN}"]
            ) as ws:
                await ws.send_json({
                    "type": "message.send",
                    "payload": {"content": message},
                    "timestamp": int(asyncio.get_event_loop().time() * 1000)
                })

                async with asyncio.timeout(120):
                    async for m in ws:
                        if m.type == aiohttp.WSMsgType.TEXT:
                            data = json.loads(m.data)
                            msg_type = data.get("type", "")
                            content = data.get("payload", {}).get("content", "")

                            # Skip non-message events (typing indicators, etc.)
                            if msg_type != "message.create":
                                continue

                            # Skip echo: if content matches what we sent, it's an ack
                            if content and content.strip() == message.strip():
                                continue

                            # Skip empty content
                            if not content:
                                continue

                            # This is the real worker response
                            print(content)
                            return
        except asyncio.TimeoutError:
            print("[Pico dispatch timeout after 120s]")
        except Exception as e:
            print(f"[Pico error: {e}]")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: pico-dispatch.py 'message'")
        sys.exit(1)

    asyncio.run(dispatch(sys.argv[1]))
