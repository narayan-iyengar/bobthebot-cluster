---
name: Bob v2 Build Plan
description: Step-by-step build plan for distributed cluster architecture
type: project
originSessionId: c012232c-a22f-41df-adda-157f1d6e9059
---
## Build Plan (ordered, each step builds on the previous)

### Step 1: HTTP Worker for Zeros
- Build worker.py (~50 lines): Flask/aiohttp server on port 5000
- POST /task accepts JSON, calls Gemini via proxy, runs tools, returns JSON
- POST /health returns status
- Deploy to all 8 zeros (currently 4, expanding to 8)
- Test: `curl http://p1:5000/task -d '{"task":"what is 2+2"}'`

### Step 2: Update bob.py Dispatch
- Replace pico-dispatch.py with HTTP calls to workers
- `aiohttp.ClientSession().post("http://p1:5000/task", json={"task": "..."})`
- Parallel dispatch: `asyncio.gather(*[dispatch(worker, task) for ...])` 
- Worker discovery: list of worker IPs in config.json
- Health check: ping /health on each worker, skip dead ones

### Step 3: Kill PicoClaw on RPi4
- Stop and disable: picoclaw-launcher, pico-auth-proxy, picoclaw-gateway
- Remove PicoClaw binary from RPi4 (keep on zeros until Step 1 is done)
- Remove ~/.picoclaw/ directory on RPi4 (tools already copied elsewhere)
- Clean systemd: remove old service files

### Step 4: Systemd Services for Workers
- Create worker.service on each zero (systemd)
- Auto-start on boot, restart on failure
- Kill PicoClaw on zeros, replace with worker.py

### Step 5: Distributed 7B (RPi4s only)
- RPi4-2: llama-server (main process, connects to RPi4-1 RPC)
- RPi4-1: llama-cpp rpc-server (contributes CPU + RAM)
- Download Llama 3.1 8B or Mistral 7B Q4_K_M
- Test: `curl http://rpi4-2:8080/v1/chat/completions`
- Update supervisor.py to use distributed 7B instead of 1B

### Step 6: n8n on RPi4-2
- Install n8n via Docker on RPi4-2
- Build starter workflows:
  - Morning briefing (cron trigger -> fetch tools -> Telegram)
  - Email watcher (poll Gmail -> filter keywords -> alert)
  - Traffic alert (check calendar -> if event in 30min -> check traffic -> alert)
- n8n triggers bob.py via HTTP webhook

### Step 7: Async Task Queue
- SQLite task table in bob.py
- States: queued -> running -> pending_approval -> approved -> done
- Telegram inline keyboards for approve/reject
- Long-running tasks: bob.py dispatches to worker, saves task_id, sends "working on it"
- Worker completes -> bob.py sends result to Telegram with approve/reject if needed

### Step 8: Zero Ws as RPC Nodes (13B)
- Build llama.cpp for armv6 (cross-compile or native build on zero)
- Run rpc-server on each zero (contributes ~300MB RAM each)
- RPi4-2 llama-server connects to all RPC nodes
- Total pool: ~12GB, fits 13B Q4_K_M
- Speed: ~0.5-1 tok/s (async only, 2-5 min per response)

### Step 9: Multi-user
- Add Maighna's Telegram ID to bob.py allow list
- Per-user conversation history in SQLite
- Workers handle concurrent requests naturally (HTTP)

### Step 10: Hardening
- Health monitoring: bob.py checks worker health periodically
- Auto-failover: skip dead workers, retry on healthy ones
- Log rotation for bob.py and workers
- Rate limiting on Gemini API calls
- Backup config.json and bob.db

## Current Status
- Step 1: DONE - worker.py deployed to all 4 zeros via NFS
- Step 2: DONE - bob.py dispatches via HTTP, no pico protocol
- Step 3: DONE - PicoClaw removed from RPi4, zeros run worker.py
- Step 4: DONE - workers as systemd services, auto-start on boot
- Step 5: DONE - Distributed Llama 3.1 8B across RPi4-1 (RPC) + RPi4-2 (server)
- Steps 6-10: NOT STARTED

## What's Working Today
- bob.py on RPi4-1: Telegram + Gemini + direct tools (stable)
- gemini-proxy on RPi4-1: serves workers on port 8787
- llama-rpc on RPi4-1: RPC worker contributing 2.3GB/16 layers
- llama-server on RPi4-2: distributed 8B server on port 8080 (0.8 tok/s)
- worker.py on p1,p2,p3,p4: HTTP task workers on port 5000
- Morning briefing via cron at 7am weekdays
- All tools: calendar, email, weather, traffic
- GitHub repo: narayan-iyengar/bobthebot-cluster
