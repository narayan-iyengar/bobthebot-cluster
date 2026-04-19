#!/bin/bash
# Refresh Google Calendar token and sync to workers
python3 << 'PYEOF'
import json, urllib.request, urllib.parse
from datetime import datetime

with open("/home/narayan/.bob/gcal-token.json") as f:
    t = json.load(f)

data = urllib.parse.urlencode({
    "client_id": t["client_id"],
    "client_secret": t["client_secret"],
    "refresh_token": t["refresh_token"],
    "grant_type": "refresh_token",
}).encode()

req = urllib.request.Request(
    "https://oauth2.googleapis.com/token",
    data=data,
    headers={"Content-Type": "application/x-www-form-urlencoded"},
)

with urllib.request.urlopen(req) as resp:
    new = json.loads(resp.read())

t["access_token"] = new["access_token"]
t["expires_at"] = datetime.now().timestamp() + new.get("expires_in", 3600)

with open("/home/narayan/.bob/gcal-token.json", "w") as f:
    json.dump(t, f, indent=2)
PYEOF

# Sync to all nodes via NFS (instant, no SSH needed)
for n in p1 p2 p3 p4; do
    NFS="/var/lib/clusterctrl/nfs/$n/home/narayan/.bob"
    if [ -d "$NFS" ]; then
        cp -f ~/.bob/gcal-token.json "$NFS/gcal-token.json" 2>/dev/null
    fi
done
