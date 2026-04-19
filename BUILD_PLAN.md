# BobTheBot Build Plan

## Completed Steps

### Step 1: HTTP Workers ✅
- worker.py: lightweight HTTP server on each Pi Zero W
- POST /task accepts JSON, calls Gemini via proxy, runs tools, returns result
- GET /health returns status
- Deployed to all 4 zeros via NFS

### Step 2: bob.py HTTP Dispatch ✅
- Replaced PicoClaw + pico protocol with direct HTTP calls to workers
- Health check before dispatch, auto-failover to next healthy worker
- Fallback: if all workers down, Bob calls Gemini directly
- Worker list in config.json

### Step 3: PicoClaw Removal ✅
- Stopped and disabled: picoclaw-launcher, pico-auth-proxy, picoclaw-gateway
- No PicoClaw processes anywhere in the cluster
- All dispatch via HTTP

### Step 4: Systemd Services ✅
- worker.service on each zero (auto-start, restart on failure)
- bob.service on RPi4-1 (with loginctl linger for persistence)
- gemini-proxy.service on RPi4-1
- llama-rpc.service on RPi4-1
- llama-server.service on RPi4-2

### Step 5: Distributed LLM ✅
- Phi-4 Mini 3.8B Q4_K_M (2.4GB) distributed across two RPi4s
- RPi4-2: llama-server (1.8GB local, 10 layers)
- RPi4-1: rpc-server (1.0GB, contributes CPU + RAM)
- Performance: 1.6 tok/s generate, ~55s for supervisor review
- Used for: privacy-sensitive tasks, supervisor pre-filter, offline fallback
- Gemini handles 95% of tasks (faster, more accurate, free tier)

## Remaining Steps

### Step 6: n8n on RPi4-2
- Install n8n via Docker
- Build event-driven workflows:
  - Email watcher (poll Gmail -> filter keywords -> alert via Telegram)
  - Pre-event traffic alert (check calendar -> if event in 30min -> check traffic -> alert)
  - Weekly schedule digest (Sunday evening summary of upcoming week)
- n8n triggers bob.py via HTTP webhook

### Step 7: Approval Gates
- Telegram inline keyboards for approve/reject on outbound actions
- SQLite pending_actions table (already in bob.py schema)
- Flow: Bob shows draft/action -> user taps Approve -> Bob executes
- Applies to: calendar add/delete, email drafts

### Step 9: Multi-user
- Add Maighna's Telegram ID to config.json allow list
- Per-user conversation history in SQLite (already supported)
- Workers handle concurrent requests naturally (HTTP)

### Step 10: Hardening
- Health monitoring: bob.py checks worker health periodically
- Log rotation for bob.py and workers
- Backup config.json and bob.db

## What's Running

| Node | Services | Purpose |
|------|----------|---------|
| RPi4-1 | bob.py, gemini-proxy, llama-rpc | Controller: Telegram, tools, RPC |
| RPi4-2 | llama-server (Phi-4 Mini 3.8B) | Distributed local LLM |
| p1-p4 | worker.py | HTTP task agents |

## Performance

| Operation | Speed | LLM |
|-----------|-------|-----|
| Calendar/email query | 2-3s | Gemini |
| Weather | 1s | Gemini |
| Traffic | 1s | Gemini |
| Worker dispatch | 5-15s | Gemini (via proxy) |
| Local LLM review | ~55s | Phi-4 Mini (no cloud) |
| Morning briefing | 5-8s | Direct tools |
