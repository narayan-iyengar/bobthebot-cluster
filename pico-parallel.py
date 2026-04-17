#!/usr/bin/env python3
"""
Batch dispatch to cluster workers via pico protocol.
Sends tasks sequentially (pico protocol handles one at a time),
but each task goes to a different worker via round-robin.
Usage: pico-parallel.py 'task1' 'task2' 'task3'
Returns JSON array of results.
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


async def get_cookie():
    async with aiohttp.ClientSession() as s:
        async with s.get(
            f"{LAUNCHER_URL}/?token={DASHBOARD_TOKEN}",
            allow_redirects=False
        ) as r:
            c = r.cookies.get("picoclaw_launcher_auth")
            return c.value if c else None


async def dispatch_one(cookie, task, timeout_s=60):
    """Dispatch a single task via pico WebSocket."""
    cookies = {"picoclaw_launcher_auth": cookie}
    async with aiohttp.ClientSession(cookies=cookies) as s:
        try:
            async with s.ws_connect(
                "ws://localhost:18800/pico/ws",
                protocols=[f"token.{PICO_TOKEN}"]
            ) as ws:
                await ws.send_json({
                    "type": "message.send",
                    "payload": {"content": task},
                    "timestamp": int(asyncio.get_event_loop().time() * 1000)
                })
                async with asyncio.timeout(timeout_s):
                    async for m in ws:
                        if m.type == aiohttp.WSMsgType.TEXT:
                            data = json.loads(m.data)
                            if data.get("type") != "message.create":
                                continue
                            content = data.get("payload", {}).get("content", "")
                            if not content:
                                continue
                            # Skip echo of sent message
                            if content.strip() == task.strip():
                                continue
                            return content
        except asyncio.TimeoutError:
            return "[timeout]"
        except Exception as e:
            return f"[error: {e}]"
    return "[no response]"


async def main(tasks):
    cookie = await get_cookie()
    if not cookie:
        print(json.dumps(["[auth failed]"] * len(tasks)))
        return

    # Sequential dispatch, each on a fresh pico connection
    # Launcher round-robins to different workers
    results = []
    for task in tasks:
        result = await dispatch_one(cookie, task)
        results.append(result)

    print(json.dumps(results))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: pico-parallel.py 'task1' 'task2' ...")
        sys.exit(1)

    asyncio.run(main(sys.argv[1:]))
