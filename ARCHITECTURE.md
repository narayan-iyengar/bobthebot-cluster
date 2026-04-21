# BobTheBot Cluster Architecture

## Hardware
- 2x RPi4 4GB (aarch64, Cortex-A72 quad-core)
- 8x Pi Zero W 512MB (armv6, single-core)
- ClusterHAT v2.5 on RPi4-1, ClusterHAT v2.6 on RPi4-2

## Architecture

```
┌─────────────────────────────────────────────────────┐
│              RPi4-1 (Controller)                    │
│                                                     │
│  bob.py         Telegram + Gemini + parallel dispatch│
│  gemini-proxy   API key proxy for workers (:8787)   │
│  llama-rpc      Contributes 1.0GB to Phi-4 Mini    │
│  tools          calendar, email, weather, traffic   │
│  bob.db         SQLite conversation history         │
│                                                     │
│  ClusterHAT v2.5                                    │
│  ├── p1 (172.19.181.1:5000)  worker.py             │
│  ├── p2 (172.19.181.2:5000)  worker.py             │
│  ├── p3 (172.19.181.3:5000)  worker.py             │
│  └── p4 (172.19.181.4:5000)  worker.py             │
└─────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────┐
│              RPi4-2 (Inference + Workers)            │
│                                                      │
│  llama-server   Phi-4 Mini 3.8B distributed (:8080) │
│                 1.8GB local + 1.0GB via RPC          │
│                 1.6 tok/s, privacy-sensitive tasks   │
│  iptables NAT   :5001-5004 -> zeros :5000           │
│                                                      │
│  ClusterHAT v2.6                                    │
│  ├── p1 -> exposed as 192.168.0.105:5001            │
│  ├── p2 -> exposed as 192.168.0.105:5002            │
│  ├── p3 -> exposed as 192.168.0.105:5003            │
│  └── p4 -> exposed as 192.168.0.105:5004            │
└─────────────────────────────────────────────────────┘
```

## How Tasks Flow

| You ask | What happens | Speed | LLM |
|---------|-------------|-------|-----|
| "Hi Bob" | Bob responds directly | instant | Gemini |
| "Calendar today?" | Bob runs calendar-tool.py | 2-3s | Gemini |
| "Weather?" | Bob runs weather-tool.py | 1s | Gemini |
| "Traffic to RTA?" | Bob runs traffic-tool.py | 1s | Gemini |
| [sends photo] | Gemini vision analyzes image | 3-5s | Gemini |
| "Research X" | Bob dispatches to 1 worker | 5-15s | Gemini via proxy |
| "Compare 5 things" | Bob fans out to 5 workers in parallel | 5-15s | Gemini via proxy |
| Supervisor review | Phi-4 Mini on local cluster | ~55s | Local (no cloud) |

## Parallel Dispatch

Bob has `dispatch_parallel` tool that fans out tasks across all 8 workers:
- "Compare 5 restaurants" -> 5 workers search simultaneously
- "Research camps for each kid" -> 2 workers, one per kid
- "Morning briefing" -> calendar + email + weather in parallel
- All tasks start at the same time, results collected when all finish
- Time = slowest worker, not sum of all workers

## Services

### RPi4-1 (systemd user services, linger enabled)
| Service | Port | Description |
|---------|------|-------------|
| bob.service | - | Telegram bot + Gemini orchestrator |
| gemini-proxy.service | 8787 | API key proxy for workers |
| llama-rpc.service | 50052 | RPC worker for distributed Phi-4 |

### RPi4-2 (systemd system services)
| Service | Port | Description |
|---------|------|-------------|
| llama-server.service | 8080 | Phi-4 Mini 3.8B distributed |
| iptables (rc.local) | 5001-5004 | Port forward to zeros |

### Pi Zeros (systemd system services)
| Service | Port | Description |
|---------|------|-------------|
| worker.service | 5000 | HTTP task agent |

### Cron (RPi4-1)
| Schedule | Job |
|----------|-----|
| 0 7 * * 1-5 | morning-briefing.sh |
| */45 * * * * | refresh-tokens.sh (NFS copy) |
| 0 4 * * * | clear-sessions.sh |

## Design Principles

- **Gemini for 95% of tasks**: fast (2-3s), accurate, free tier
- **Phi-4 Mini for privacy**: email summaries, personal data, offline use
- **HTTP everywhere**: workers expose POST /task, GET /health
- **Parallel by default**: 8 workers, fan out whenever possible
- **NFS deploy**: copy files to NFS root, instant deploy to zeros
- **No PicoClaw**: all custom Python
- **Stateless messages**: short sliding window (3 exchanges) for follow-ups only

## Networking

- RPi4-1 zeros: 172.19.181.1-4 (direct bridge, reachable from bob.py)
- RPi4-2 zeros: 172.19.181.1-4 (same subnet, different bridge)
  - NOT directly reachable from RPi4-1
  - Exposed via iptables NAT: 192.168.0.105:5001-5004
- Both RPi4s on home LAN: 192.168.0.42 and 192.168.0.105
