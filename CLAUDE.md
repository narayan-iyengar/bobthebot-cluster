# BobTheBot - RPi ClusterHAT Home Assistant

## Overview
RPi 4 ClusterHAT with 4 RPi Zero W nodes. Bob is a family personal assistant on Telegram.

## Network
- **RPi 4 (Bob)**: Controller node, hostname `cluster-controller`
- **Pi Zeros**: Bridge mode on 172.19.181.x, NFS-booted from controller
  - p1: 172.19.181.1, p2: 172.19.181.2, p3: 172.19.181.3, p4: 172.19.181.4
- **RPi 4-2 (cluster-llm)**: Optional local LLM node for supervisor pre-filter
- SSH user: same on all nodes. ProxyJump configured in ~/.ssh/config.

## Architecture
- **RPi4 (Bob)**: PicoClaw gateway, Telegram bot, Gemini 2.5 Flash via API key proxy
- **p1-p4 (Workers)**: PicoClaw agents, dispatched via pico protocol, use Gemini via proxy
- **cluster-llm**: llama.cpp with Llama 3.2 1B for local supervisor pre-filtering
- Direct tool calls on RPi4 for calendar, email, weather, traffic (fast path)
- Workers dispatched for LLM tasks (research, drafting, analysis)

## Tools
- `calendar-tool.py` - iCloud CalDAV + Google Calendar + ICS feeds
- `email-tool.py` - Gmail read-only
- `weather-tool.py` - Open-Meteo (free, no API key)
- `traffic-tool.py` - Google Routes + Places API
- `supervisor.py` - Local LLM pre-filter + Gemini fallback
- `pico-dispatch.py` - Single worker dispatch via pico protocol
- `pico-parallel.py` - Batch dispatch to multiple workers
- `morning-briefing.sh` - Daily briefing via cron + Telegram

## Configuration
All secrets stored in `config.json` (not committed). See `config.example.json` for format.

## Commands
- Check Bob: `systemctl --user status picoclaw-gateway`
- View logs: `tail -f ~/.picoclaw/logs/gateway.log`
- Test calendar: `python3 calendar-tool.py list`
- Test weather: `python3 weather-tool.py`
- Test traffic: `python3 traffic-tool.py "destination"`
- Clear sessions: `rm -rf ~/.picoclaw/sessions`
