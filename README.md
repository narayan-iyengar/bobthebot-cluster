# BobTheBot Cluster

A multi-agent personal home assistant running on a 10-node Raspberry Pi cluster. Bob lives on Telegram and manages your family's calendars, email, weather, traffic, and dispatches tasks to 8 worker agents in parallel.

## What it does

- **Calendar management** - iCloud + Google Calendar. List, search, add, delete events with location support
- **Email** - Gmail read-only. Check inbox, unread, search
- **Weather** - Current conditions, 3-day forecast, hourly (via Open-Meteo, free)
- **Traffic** - Real-time drive times with traffic (via Google Routes API)
- **Morning briefing** - Automated daily summary at 7am via Telegram
- **Image processing** - Send photos to Bob, Gemini vision analyzes them
- **Parallel dispatch** - Fan out tasks across 8 worker agents simultaneously
- **Distributed LLM** - Phi-4 Mini 3.8B split across two RPi4s via llama.cpp RPC

## Architecture

```
┌─────────────────────────────────────────────────────┐
│              RPi4-1 (Controller)                    │
│                                                     │
│  bob.py         Telegram + Gemini + parallel dispatch│
│  gemini-proxy   API key proxy for workers (:8787)   │
│  llama-rpc      Contributes 1.0GB to Phi-4 Mini    │
│  tools          calendar, email, weather, traffic   │
└──────────┬──────────────────────────────────────────┘
           │ HTTP dispatch (:5000)
    ┌──────┼──────┬──────┬──────┐
    p1    p2    p3    p4           4x Pi Zero W
    worker.py on each             ClusterHAT v2.5

┌─────────────────────────────────────────────────────┐
│              RPi4-2 (Inference + Workers)            │
│                                                      │
│  llama-server   Phi-4 Mini 3.8B distributed (:8080) │
│                 1.8GB local + 1.0GB via RPC          │
│  port-forward   :5001-5004 -> zeros :5000           │
└──────────┬──────────────────────────────────────────┘
           │ port forwarded via iptables
    ┌──────┼──────┬──────┬──────┐
    p1    p2    p3    p4           4x Pi Zero W
    worker.py on each             ClusterHAT v2.6

Total: 2x RPi4 (4GB) + 8x Pi Zero W (512MB) = 10 nodes
```

### How tasks flow

| Task type | Path | Time |
|-----------|------|------|
| Greetings, simple math | Bob responds directly | instant |
| Calendar/email query | Bob runs tool on RPi4 | 2-3s |
| Weather/traffic | Bob runs tool on RPi4 | 1-2s |
| Single research task | Bob dispatches to 1 worker | 5-15s |
| Multi-part research | Bob fans out to 8 workers in parallel | 5-15s |
| Image analysis | Gemini vision | 3-5s |
| Local LLM (privacy) | Phi-4 Mini distributed, 1.6 tok/s | ~60s |

## Hardware

- **Raspberry Pi 4** (4GB) x2 - Controller + inference server
- **ClusterHAT v2.5** - 4 Pi Zeros on RPi4-1
- **ClusterHAT v2.6** - 4 Pi Zeros on RPi4-2
- **8x Raspberry Pi Zero W** - HTTP worker agents (NFS boot)

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

# 5. Deploy workers to Pi Zeros (via NFS, instant)
for n in p1 p2 p3 p4; do
  sudo cp worker.py config.json calendar-tool.py email-tool.py \
         weather-tool.py traffic-tool.py \
         /var/lib/clusterctrl/nfs/$n/home/youruser/
done

# 6. Start Gemini proxy (for workers)
python3 gemini-proxy.py 8787

# 7. For second ClusterHAT on RPi4-2, port forward zeros:
sudo iptables -t nat -A PREROUTING -p tcp --dport 5001 -j DNAT --to 172.19.181.1:5000
sudo iptables -t nat -A PREROUTING -p tcp --dport 5002 -j DNAT --to 172.19.181.2:5000
sudo iptables -t nat -A PREROUTING -p tcp --dport 5003 -j DNAT --to 172.19.181.3:5000
sudo iptables -t nat -A PREROUTING -p tcp --dport 5004 -j DNAT --to 172.19.181.4:5000
sudo iptables -t nat -A POSTROUTING -j MASQUERADE
```

## Files

| File | Purpose |
|------|---------|
| `bob.py` | Main orchestrator: Telegram + Gemini function calling + parallel dispatch |
| `worker.py` | HTTP worker agent for Pi Zeros (POST /task, GET /health) |
| `calendar-tool.py` | iCloud + Google Calendar + ICS feed reader/writer |
| `email-tool.py` | Gmail read-only (inbox, search, read) |
| `weather-tool.py` | Open-Meteo weather (free, no key needed) |
| `traffic-tool.py` | Google Routes + Places API for traffic and address lookup |
| `supervisor.py` | Output verification: local LLM pre-filter + Gemini fallback |
| `gemini-proxy.py` | Gemini API key proxy for workers |
| `morning-briefing.sh` | Daily briefing (calendar + email + weather -> Telegram) |
| `gcal-auth.py` | One-time Google OAuth setup |
| `refresh-tokens.sh` | Cron: refresh Google OAuth tokens via NFS |

## Distributed LLM

Phi-4 Mini 3.8B Q4_K_M split across two RPi4s using llama.cpp RPC:

```bash
# RPi4-1: RPC worker (contributes CPU + 1.0GB RAM)
rpc-server --host 0.0.0.0 --port 50052 --threads 2

# RPi4-2: Main server (1.8GB local + 1.0GB via RPC)
llama-server --model Phi-4-mini-instruct-Q4_K_M.gguf \
    --host 0.0.0.0 --port 8080 \
    --rpc 192.168.0.42:50052 \
    --ctx-size 4096 --threads 2 -ngl 10
```

Performance: 1.6 tok/s. Used for privacy-sensitive tasks and supervisor pre-filtering. Gemini handles 95% of tasks (faster, more accurate, free tier).

## License

MIT
