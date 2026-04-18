---
name: Architecture Goals
description: Full distributed cluster architecture - Bob v2 with HTTP workers and distributed LLM
type: project
originSessionId: c012232c-a22f-41df-adda-157f1d6e9059
---
## Hardware
- 2x RPi4 4GB (aarch64, Cortex-A72 quad-core)
- 8x Pi Zero W 512MB (armv6, single-core)

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    RPi4-1 (Controller)                  │
│                                                         │
│  bob.py         - Telegram bot + Gemini + task queue    │
│  gemini-proxy   - API key proxy for workers (:8787)     │
│  llama-rpc      - RPC worker for distributed inference  │
│  tools          - calendar, email, weather, traffic     │
│  SQLite         - task queue + conversation history     │
│                                                         │
│  Dispatches tasks to workers via HTTP                   │
│  Accepts results, sends to Telegram                     │
└─────────────┬───────────────────────────────────────────┘
              │ HTTP dispatch + Gemini proxy
              │
    ┌─────────┼─────────┬─────────┬─────────┐
    │         │         │         │    ...x8 │
┌───▼───┐┌───▼───┐┌───▼───┐┌───▼───┐       │
│  p1   ││  p2   ││  p3   ││  p4   │       │
│Worker ││Worker ││Worker ││Worker │  Zero Ws
│       ││       ││       ││       │
│HTTP   ││HTTP   ││HTTP   ││HTTP   │  POST /task
│:5000  ││:5000  ││:5000  ││:5000  │  -> Gemini
│       ││       ││       ││       │  -> tools
│llama  ││llama  ││llama  ││llama  │  -> result
│rpc*   ││rpc*   ││rpc*   ││rpc*   │  *optional
└───────┘└───────┘└───────┘└───────┘

┌─────────────────────────────────────────────────────────┐
│                    RPi4-2 (Infra)                       │
│                                                         │
│  n8n            - Event-driven workflows (Docker)       │
│  llama-server   - Main inference server                 │
│                   Connects to RPi4-1 + Zero RPC workers │
│                   Serves OpenAI-compatible API (:8080)  │
│                                                         │
│  Triggers: email watch, calendar alerts, cron jobs      │
│  Calls bob.py via webhook when events fire              │
└─────────────────────────────────────────────────────────┘
```

## Layers

### Layer 1: Telegram Interface (RPi4-1)
- bob.py handles all Telegram I/O
- Classifies: instant response vs tool call vs async dispatch
- Approval gates via inline keyboards

### Layer 2: Task Workers (8x Zero Ws)
- Simple HTTP server (~50 lines Python) on each zero
- POST /task -> calls Gemini via proxy -> runs tools -> returns JSON
- Parallel dispatch: bob.py sends HTTP requests to multiple zeros simultaneously
- No PicoClaw, no pico protocol, no SSH

### Layer 3: Event Engine (RPi4-2)
- n8n handles event-driven automation
- Watch email for keywords, check traffic before calendar events
- Triggers bob.py via webhook: "event happened, here's what to do"
- Cron-based workflows (morning briefing, daily digest)

### Layer 4: Local LLM (RPi4-1 + RPi4-2 + Zero Ws)
- llama.cpp distributed inference via RPC
- RPi4-2 runs llama-server (main process)
- RPi4-1 runs rpc-server (contributes CPU + RAM)
- Zero Ws optionally run rpc-server (contribute RAM for model layers)
- Used for: async tasks where privacy matters or cloud is unavailable

#### Distributed Model Capacity
- 2x RPi4 only (8GB): 7B Q4_K_M comfortably, ~3-6 tok/s
- 2x RPi4 + 8 Zero Ws (~12GB usable): 13B Q4_K_M fits
  - RPi4s handle bulk of compute (fast layers)
  - Zeros hold extra layers in RAM (slow but adds capacity)
  - Estimated: ~0.5-1 tok/s (bottlenecked by Zero W compute)
  - 150 token response = 2-5 minutes. Fine for async dispatch.

## Design Principles
- No outbound actions without user approval (inline keyboard gates)
- HTTP everywhere (no PicoClaw, no pico protocol, no SSH dispatch)
- Adding a worker = copy worker.py + point at proxy
- Tools as subprocess calls (existing scripts, battle-tested)
- Gemini for speed-critical tasks, local 7B/13B for privacy/async tasks
- SQLite for task queue (no Redis, no Celery)

## Build Order
1. HTTP worker for zeros (worker.py, ~50 lines)
2. Update bob.py dispatch to HTTP
3. Kill all PicoClaw on RPi4 (launcher, gateway, auth-proxy)
4. Install n8n on RPi4-2
5. Set up distributed 7B across RPi4s via llama.cpp RPC
6. Add Zero Ws as optional RPC nodes for 13B
7. Build async task queue with approval gates
