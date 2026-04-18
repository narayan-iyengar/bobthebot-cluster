# BobTheBot Cluster

A multi-agent personal home assistant running on a Raspberry Pi cluster. Bob lives on Telegram and manages your family's calendars, email, weather, traffic, and dispatches research tasks to worker agents.

## What it does

- **Calendar management** - iCloud + Google Calendar. List, search, add, delete events with location support
- **Email** - Gmail read-only. Check inbox, unread, search
- **Weather** - Current conditions, 3-day forecast, hourly (via Open-Meteo, free)
- **Traffic** - Real-time drive times with traffic (via Google Routes API)
- **Morning briefing** - Automated daily summary at 7am via Telegram
- **Multi-agent dispatch** - Fan out research/drafting tasks to HTTP worker agents on Pi Zeros
- **Distributed LLM** - Llama 3.1 8B split across two RPi4s via llama.cpp RPC for local inference

## Architecture

```
┌─────────────────────────────────────────────────────┐
│              RPi4-1 (Controller)                    │
│                                                     │
│  bob.py       - Telegram bot + Gemini + task router │
│  gemini-proxy - API key proxy for workers (:8787)   │
│  llama-rpc    - RPC worker for distributed LLM      │
│  tools        - calendar, email, weather, traffic   │
│                                                     │
│  Dispatches to workers via HTTP                     │
└──────────┬──────────────────────────────────────────┘
           │ HTTP (POST /task, GET /health)
           │
  ┌────────┼────────┬────────┬────────┐
  │        │        │        │        │
┌─▼──┐ ┌──▼─┐ ┌──▼─┐ ┌──▼─┐      │
│ p1 │ │ p2 │ │ p3 │ │ p4 │  ... │ Pi Zero W
│HTTP│ │HTTP│ │HTTP│ │HTTP│      │ workers
│5000│ │5000│ │5000│ │5000│      │
└────┘ └────┘ └────┘ └────┘      │
                                   │
┌─────────────────────────────────────────────────────┐
│              RPi4-2 (Inference + Infra)              │
│                                                      │
│  llama-server  - Distributed 8B inference (:8080)    │
│                  16 layers local + 16 layers via RPC │
│  n8n           - Event-driven workflows (planned)    │
└──────────────────────────────────────────────────────┘
```

### How tasks flow

| Task type | Path | Time |
|-----------|------|------|
| Greetings, simple math | Bob responds directly | instant |
| Calendar/email query | Bob runs tool on RPi4 | 2-3s |
| Weather/traffic | Bob runs tool on RPi4 | 1-2s |
| Research, drafting | Bob dispatches to worker via HTTP | 5-15s |
| Local LLM (async) | Distributed 8B across RPi4s | ~4 min/response |

## Hardware

- **Raspberry Pi 4** (4GB) x2 - Controller + inference server
- **ClusterHAT v2.5** - Connects up to 4 Pi Zeros
- **4-8x Raspberry Pi Zero W** - HTTP worker agents (NFS boot from controller)

## Prerequisites

- Gemini API key (free tier at [aistudio.google.com](https://aistudio.google.com))
- Telegram bot token (via [@BotFather](https://t.me/BotFather))
- iCloud app-specific password (for CalDAV)
- Google Cloud project with Calendar + Gmail OAuth
- Google Maps API key with Routes + Places APIs enabled (for traffic)
- Python 3.11+ with `python-telegram-bot`, `caldav`, `duckduckgo-search`

## Quick start

```bash
# 1. Clone and configure
git clone https://github.com/narayan-iyengar/bobthebot-cluster.git
cd bobthebot-cluster
cp config.example.json config.json
cp bob.example.py bob.py
# Edit config.json with your API keys
# Edit bob.py with your family info and locations

# 2. Google OAuth setup
python3 gcal-auth.py

# 3. Install dependencies
pip3 install python-telegram-bot caldav duckduckgo-search

# 4. Start Bob
python3 bob.py

# 5. Deploy workers to Pi Zeros (via NFS)
# Copy worker.py + tools to each zero's NFS root
sudo cp worker.py config.json calendar-tool.py email-tool.py \
       weather-tool.py traffic-tool.py \
       /var/lib/clusterctrl/nfs/p1/home/youruser/

# 6. Start Gemini proxy (for workers)
python3 gemini-proxy.py 8787
```

## Files

| File | Purpose |
|------|---------|
| `bob.py` | Main orchestrator: Telegram + Gemini function calling + tool dispatch |
| `worker.py` | HTTP worker agent for Pi Zeros (POST /task, GET /health) |
| `calendar-tool.py` | iCloud + Google Calendar + ICS feed reader/writer |
| `email-tool.py` | Gmail read-only (inbox, search, read) |
| `weather-tool.py` | Open-Meteo weather (free, no key needed) |
| `traffic-tool.py` | Google Routes + Places API for traffic and address lookup |
| `supervisor.py` | Output verification: local LLM pre-filter + Gemini fallback |
| `gemini-proxy.py` | Gemini API key proxy for workers |
| `morning-briefing.sh` | Daily briefing (calendar + email + weather -> Telegram) |
| `gcal-auth.py` | One-time Google OAuth setup |
| `refresh-tokens.sh` | Cron: refresh Google OAuth tokens every 45 min |

## Distributed LLM

Llama 3.1 8B Q4_K_M split across two RPi4s using llama.cpp RPC:

```bash
# RPi4-1: RPC worker (contributes CPU + 2.3GB RAM)
rpc-server --host 0.0.0.0 --port 50052 --threads 2

# RPi4-2: Main server (connects to RPi4-1, loads remaining layers locally)
llama-server --model Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf \
    --host 0.0.0.0 --port 8080 \
    --rpc 192.168.0.42:50052 \
    --ctx-size 4096 --threads 2 -ngl 16
```

Performance: ~0.8 tok/s. Best for async tasks dispatched in background.

## License

MIT
