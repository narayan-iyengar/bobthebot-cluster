# BobTheBot Cluster Architecture

## Hardware
- 2x RPi4 4GB (aarch64, Cortex-A72 quad-core)
- 4x Pi Zero W 512MB (armv6, single-core) via ClusterHAT

## Architecture

```
┌─────────────────────────────────────────────────┐
│              RPi4-1 (Controller)                │
│                                                 │
│  bob.py          Telegram bot + Gemini brain    │
│  gemini-proxy    API key proxy (:8787)          │
│  llama-rpc       Contributes 1.0GB to Phi-4    │
│  tools           cal/email/weather/traffic      │
│  bob.db          SQLite conversation history    │
└────────┬────────────────────────────────────────┘
         │ HTTP dispatch (:5000)
    ┌────┼────┬────┬────┐
    │    │    │    │    │
   p1   p2   p3   p4   4x Pi Zero W
   worker.py on each   HTTP task agents
   POST /task           call Gemini via proxy
   GET /health          run tools locally

┌─────────────────────────────────────────────────┐
│              RPi4-2 (Inference + Infra)          │
│                                                  │
│  llama-server    Phi-4 Mini 3.8B (:8080)         │
│                  1.8GB local + 1.0GB via RPC     │
│                  1.6 tok/s distributed            │
│                                                  │
│  n8n             Event engine (planned)           │
└──────────────────────────────────────────────────┘
```

## How Tasks Flow

| You ask | What happens | Speed | LLM |
|---------|-------------|-------|-----|
| "Hi Bob" | Bob responds directly | instant | Gemini |
| "Calendar today?" | Bob runs calendar-tool.py | 2-3s | Gemini |
| "Weather?" | Bob runs weather-tool.py | 1s | Gemini |
| "Traffic to RTA?" | Bob runs traffic-tool.py | 1s | Gemini |
| "Research X" | Bob dispatches to a zero worker | 5-15s | Gemini (via proxy) |
| Supervisor review | Phi-4 Mini on local cluster | ~55s | Local (no cloud) |
| Privacy-sensitive | Phi-4 Mini on local cluster | ~30-60s | Local (no cloud) |

## Design Principles

- **Gemini for 95% of tasks**: fast (2-3s), accurate, free tier
- **Phi-4 Mini for privacy**: email summaries, personal data, offline use
- **HTTP everywhere**: no PicoClaw, no pico protocol, no SSH dispatch
- **Adding a worker** = copy worker.py + point at proxy
- **Tools as subprocess calls**: existing scripts, battle-tested
- **No outbound actions without approval**: approval gates for calendar writes
- **SQLite for state**: no Redis, no Celery, right-sized for personal use

## Services

### RPi4-1 (systemd user services)
| Service | Description |
|---------|-------------|
| bob.service | Telegram bot + Gemini orchestrator |
| gemini-proxy.service | API key proxy for workers on :8787 |
| llama-rpc.service | RPC worker contributing 1.0GB to distributed Phi-4 |

### RPi4-2 (systemd system services)
| Service | Description |
|---------|-------------|
| llama-server.service | Phi-4 Mini 3.8B distributed server on :8080 |

### Pi Zeros (systemd system services)
| Service | Description |
|---------|-------------|
| worker.service | HTTP task agent on :5000 |

### Cron (RPi4-1)
| Schedule | Job |
|----------|-----|
| 0 7 * * 1-5 | morning-briefing.sh (calendar + email + weather -> Telegram) |
| */45 * * * * | refresh-tokens.sh (Google Calendar OAuth token refresh via NFS) |
| 0 4 * * * | clear-sessions.sh (nightly cleanup) |

## Deployment

Workers deployed via NFS filesystem (instant, no SCP):
```bash
sudo cp worker.py tools config.json /var/lib/clusterctrl/nfs/p1/home/narayan/
```

## Future (remaining build plan steps)
- **n8n on RPi4-2**: Event-driven automation (email watch, pre-event traffic alerts)
- **Approval gates**: Telegram inline keyboards for approve/reject on calendar writes
- **Multi-user**: Add family members to Telegram allow list
