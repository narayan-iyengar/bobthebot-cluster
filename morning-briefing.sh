#!/bin/bash
WORKSPACE="/home/narayan/.picoclaw/workspace"
cd "$WORKSPACE"

python3 << 'PYEOF'
import subprocess, urllib.request, urllib.parse, re
from datetime import datetime, timezone, timedelta

PST = timezone(timedelta(hours=-7))
NOW = datetime.now(PST)
TODAY = NOW.strftime("%Y-%m-%d")
import os as _os
_cfg_path = _os.path.join(_os.path.dirname(_os.path.abspath("__file__")), "config.json")
# Try workspace dir first, then script dir
for _p in ["/home/narayan/.picoclaw/workspace/config.json", _cfg_path]:
    if _os.path.exists(_p):
        _cfg_path = _p
        break
with open(_cfg_path) as _f:
    _tcfg = json.load(_f)
BOT_TOKEN = _tcfg["telegram"]["bot_token"]
CHAT_ID = _tcfg["telegram"]["chat_id"]

def run(cmd):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)
        return r.stdout.strip()
    except:
        return ""

def parse_dt(s):
    """Parse datetime string, handle both space and T separator, convert to Pacific."""
    s = s.strip()
    # Normalize space separator to T
    s = re.sub(r'(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})', r'\1T\2', s)
    try:
        dt = datetime.fromisoformat(s)
        return dt.astimezone(PST)
    except:
        return None

def format_calendar(raw):
    events = []
    for line in raw.split("\n"):
        if not line.strip():
            continue
        # Match: [Calendar] datetime - datetime: Title
        m = re.match(r'\[(\w+)\]\s+(.+?)\s+-\s+(.+?):\s+(.*)', line)
        if not m:
            continue
        cal, start_s, end_s, title = m.group(1), m.group(2), m.group(3), m.group(4)
        dt1 = parse_dt(start_s)
        dt2 = parse_dt(end_s)
        if not dt1:
            continue
        if dt1.strftime("%Y-%m-%d") != TODAY:
            continue
        t1 = dt1.strftime("%-I:%M %p")
        t2 = dt2.strftime("%-I:%M %p") if dt2 else ""
        loc = ""
        if " @ " in title:
            title, loc_str = title.rsplit(" @ ", 1)
            loc = "\n      📍 " + loc_str.strip()
        events.append((dt1, f"  {t1} - {t2}  <b>{title.strip()}</b>{loc}"))
    events.sort(key=lambda x: x[0])
    return "\n".join(e[1] for e in events) if events else "  No events today"

def format_email(raw):
    emails = []
    lines = raw.split("\n")
    i = 0
    while i < len(lines) and len(emails) < 5:
        line = lines[i].strip()
        if line.startswith("[NEW] From:") or (line.startswith("From:") and i > 0):
            sender = line.split("From:")[-1].strip()
            name_match = re.match(r"['\"]?(.+?)['\"]?\s*<", sender)
            name = name_match.group(1).strip() if name_match else sender.split("<")[0].strip()
            # Find subject in next few lines
            subject = ""
            for j in range(i+1, min(i+5, len(lines))):
                sline = lines[j].strip()
                if sline.startswith("Subject:"):
                    subject = sline.replace("Subject:", "").strip()
                    break
            if subject:
                emails.append(f"  <b>{subject}</b>\n    from {name}")
        i += 1
    return "\n".join(emails) if emails else "  No unread emails"

# Gather
cal_raw = run("python3 calendar-tool.py list --days 1")
email_raw = run("python3 email-tool.py unread")
weather_raw = run("python3 weather-tool.py")

# Parse weather
w_lines = weather_raw.split("\n")
condition = next((l.split(":",1)[1].strip() for l in w_lines if "Condition:" in l), "")
temp = next((l.split(":",1)[1].strip() for l in w_lines if "Temperature:" in l), "")
wind = next((l.split(":",1)[1].strip() for l in w_lines if "Wind:" in l), "")

# Count unread
count_match = re.search(r"(\d+) unread", email_raw)
email_count = count_match.group(1) if count_match else "0"

msg = f"""Good morning! ☀️

<b>📅 {NOW.strftime('%A, %B %-d')}</b>

<b>🌤 Weather</b>
  {condition}, {temp}
  Wind: {wind}

<b>📋 Schedule</b>
{format_calendar(cal_raw)}

<b>📧 Email ({email_count} unread)</b>
{format_email(email_raw)}"""

data = urllib.parse.urlencode({
    "chat_id": CHAT_ID,
    "text": msg,
    "parse_mode": "HTML",
}).encode()
req = urllib.request.Request(
    f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
    data=data
)
try:
    urllib.request.urlopen(req, timeout=10)
except Exception as e:
    print(f"Send failed: {e}")
PYEOF
