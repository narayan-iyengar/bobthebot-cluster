# BobTheBot Cluster

A personal home assistant running on a Raspberry Pi ClusterHAT. Bob lives on Telegram and helps your family with calendars, email, weather, traffic, and more.

## What it does

- **Calendar management** - iCloud + Google Calendar. List, search, add, delete events with location support
- **Email** - Gmail read-only. Check inbox, unread, search
- **Weather** - Current conditions, 3-day forecast, hourly (via Open-Meteo, free)
- **Traffic** - Real-time drive times with traffic (via Google Routes API)
- **Morning briefing** - Automated daily summary at 7am via Telegram
- **Multi-agent dispatch** - Fan out tasks to worker nodes for parallel processing
- **Supervisor** - Local LLM pre-filter with cloud fallback for output verification

## Architecture

```
┌──────────────────────────────────────────────────┐
│         RPi 4 (Controller / Bob)                 │
│                                                  │
│  Telegram ──> PicoClaw Gateway ──> Gemini API    │
│                    │                             │
│  Tools: calendar, email, weather, traffic        │
│  Supervisor: local LLM pre-filter                │
│  Dispatch: pico-dispatch.py / pico-parallel.py   │
│                    │                             │
│              pico protocol                       │
└────────┬───────┬───────┬───────┬─────────────────┘
         │       │       │       │
    ┌────▼──┐┌───▼──┐┌───▼──┐┌───▼──┐
    │  p1   ││  p2  ││  p3  ││  p4  │  Pi Zero W workers
    │Worker ││Worker││Worker││Worker│  PicoClaw + Gemini
    └───────┘└──────┘└──────┘└──────┘

┌──────────────────────┐
│  RPi 4-2 (optional)  │
│  llama.cpp server    │  Local LLM for supervisor
│  Llama 3.2 1B Q4_K_M │  pre-filtering
└──────────────────────┘
```

### How tasks flow

| Task type | Path | Time |
|-----------|------|------|
| Greetings, simple math | Bob responds directly | instant |
| Calendar/email query | Bob runs tool locally | 2-5s |
| Weather/traffic | Bob runs tool locally | 1-2s |
| Research, drafting | Bob dispatches to one worker | 3-5s |
| Multi-part questions | Bob dispatches to multiple workers | 4-8s |
| Supervisor review | Local LLM (approve) or Gemini (verify) | 2-10s |

## Hardware

- **Raspberry Pi 4** (4GB) - Controller running Bob
- **ClusterHAT v2.5** - Connects up to 4 Pi Zeros
- **4x Raspberry Pi Zero W** - Worker nodes (NFS boot from controller)
- **Raspberry Pi 4** (4GB, optional) - Local LLM server

Total cost: ~$150-200 depending on what you have lying around.

## Prerequisites

- [PicoClaw](https://picoclaw.com) installed on RPi4 (aarch64) and Pi Zeros (armv6)
- Gemini API key (free tier at [aistudio.google.com](https://aistudio.google.com))
- Telegram bot token (via [@BotFather](https://t.me/BotFather))
- iCloud app-specific password (for CalDAV)
- Google Cloud project with Calendar + Gmail OAuth (for Google Calendar and email)
- Google Maps API key with Routes + Places APIs enabled (for traffic)
- Python 3.11+ with `caldav` and `aiohttp` packages

## Setup

### 1. Clone and configure

```bash
git clone https://github.com/yourusername/bobthebot-cluster.git
cd bobthebot-cluster
cp config.example.json config.json
# Edit config.json with your API keys, tokens, and passwords
```

### 2. Google OAuth setup (Calendar + Gmail)

```bash
# Create a GCP project, enable Calendar API and Gmail API
# Create OAuth credentials (Desktop app)
# Add client_id and client_secret to config.json
python3 gcal-auth.py
# Follow the prompts to authorize
```

### 3. Deploy to RPi4

```bash
# Copy all tools to PicoClaw workspace
cp *.py ~/.picoclaw/workspace/
cp config.json ~/.picoclaw/workspace/

# Copy agent.example.md and customize for your family
cp agent.example.md ~/.picoclaw/workspace/AGENT.md
# Edit AGENT.md with your family members, locations, calendars
```

### 4. Configure PicoClaw

Set up `~/.picoclaw/config.json`:
- Model: point to Gemini via API key proxy or directly
- Channels: enable Telegram with your bot token and user ID
- Pico: enable pico server for worker dispatch
- Exec: add tool scripts to `custom_allow_patterns`

### 5. Gemini API proxy (for workers)

The workers (Pi Zeros) can't use API keys directly through PicoClaw. Run a proxy on the controller:

```bash
# gemini-proxy.py proxies OpenAI-compatible requests to Gemini
# Workers point their model config to http://controller-ip:8787/v1
python3 gemini-proxy.py 8787
```

### 6. Deploy to workers

```bash
for node in p1 p2 p3 p4; do
  scp calendar-tool.py email-tool.py weather-tool.py traffic-tool.py config.json $node:~/.picoclaw/workspace/
done
```

### 7. Morning briefing (optional)

```bash
# Add to crontab
crontab -e
# Add: 0 7 * * 1-5 /path/to/morning-briefing.sh
```

### 8. Local LLM supervisor (optional)

```bash
# On a separate RPi4 or any Linux box
# Build llama.cpp from source
git clone --depth 1 https://github.com/ggerganov/llama.cpp.git
cd llama.cpp && cmake -B build && cmake --build build -j4
sudo cp build/bin/llama-server /usr/local/bin/

# Download a small model
wget -O model.gguf "https://huggingface.co/bartowski/Llama-3.2-1B-Instruct-GGUF/resolve/main/Llama-3.2-1B-Instruct-Q4_K_M.gguf"

# Run
llama-server --model model.gguf --host 0.0.0.0 --port 8080 --ctx-size 8192 --threads 4
```

## Files

| File | Purpose |
|------|---------|
| `calendar-tool.py` | iCloud + Google Calendar + ICS feed reader/writer |
| `email-tool.py` | Gmail read-only (inbox, search, read) |
| `weather-tool.py` | Open-Meteo weather (free, no key needed) |
| `traffic-tool.py` | Google Routes + Places API for traffic and address lookup |
| `supervisor.py` | Output verification: local LLM pre-filter + Gemini fallback |
| `pico-dispatch.py` | Dispatch single task to worker via pico protocol |
| `pico-parallel.py` | Batch dispatch multiple tasks to workers |
| `morning-briefing.sh` | Daily briefing script (calendar + email + weather via Telegram) |
| `gcal-auth.py` | One-time Google OAuth setup |
| `gemini-proxy.py` | Gemini API key proxy for workers |
| `refresh-tokens.sh` | Cron script to refresh Google OAuth tokens |
| `agent.example.md` | Example AGENT.md (customize for your family) |
| `config.example.json` | Example config with placeholder secrets |

## Customization

### Adding your family
Edit `AGENT.md` with your family members, their activities, and calendar conventions. Bob uses this to understand who's who and route questions correctly.

### Adding locations
Add frequently visited addresses to the "Known locations" section of `AGENT.md`. Bob will use these for traffic queries instead of looking them up each time.

### Adding calendars
The calendar tool supports:
- **iCloud CalDAV** - read/write (needs app-specific password)
- **Google Calendar API** - read/write (needs OAuth)
- **ICS feeds** - read-only (just add the URL to `ICS_FEEDS` in calendar-tool.py)

### Weather location
Edit the `LAT` and `LON` variables in `weather-tool.py` for your location.

## Performance

Measured on RPi 4 (Cortex-A72, 4GB):

| Operation | Time |
|-----------|------|
| Calendar query (direct) | 2-3s |
| Weather check | <1s |
| Traffic check | 1-2s |
| Worker dispatch (pico) | 1.5-3s |
| Supervisor (local 1B approve) | 7-10s |
| Supervisor (Gemini fallback) | 2-5s |
| Morning briefing generation | 5-8s |

## Limitations

- **Local LLM as brain**: ARM is too slow. The system prompt (~5000 tokens) takes 8+ minutes to process on a 1B model. Gemini stays as the brain.
- **Parallel pico dispatch**: The pico protocol doesn't support true parallel WebSocket sessions. Batch dispatch runs sequentially (~1.4s per task).
- **Real-time traffic**: Requires Google Maps API (Routes + Places). Free tier covers ~40K requests/month.
- **Calendar writes**: iCloud CalDAV only. Google Calendar writes work but are secondary.

## License

MIT
