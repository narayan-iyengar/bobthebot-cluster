#!/usr/bin/env python3
"""
Unified Calendar tool for the cluster.
Reads/writes iCloud (Family, Home) and Google Calendar (Personal).

Usage:
  calendar-tool.py list [--days N]
  calendar-tool.py add "title" "start" "end" [--calendar NAME]
  calendar-tool.py search "query"
"""

import sys
import json
import os
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timedelta

import caldav

# Load config
_cfg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
with open(_cfg_path) as _f:
    _cfg = json.load(_f)

ICLOUD_URL = _cfg["icloud"]["url"]
ICLOUD_USER = _cfg["icloud"]["username"]
ICLOUD_PASS = _cfg["icloud"]["password"]
GCAL_TOKEN_FILE = _cfg["google"]["token_file"]
GCAL_CLIENT_ID = _cfg["google"]["client_id"]
GCAL_CLIENT_SECRET = _cfg["google"]["client_secret"]

DEFAULT_CALENDAR = "Family"
SKIP_CALENDARS = {"Reminders", "Holidays in United States"}

# Subscribed ICS feeds (read-only)
ICS_FEEDS = {
    "Elements": "https://calendar.sportsyou.com/access/us-c2d05145-7e56-4a22-b1f6-3506414e2eb1/ce8e163f-6a8f-4aa5-9d8e-80985f655910",
}


def gcal_get_token():
    with open(GCAL_TOKEN_FILE) as f:
        token = json.load(f)

    expires_at = token.get("expires_at", 0)
    if expires_at and datetime.now().timestamp() > expires_at - 60:
        data = urllib.parse.urlencode({
            "client_id": GCAL_CLIENT_ID,
            "client_secret": GCAL_CLIENT_SECRET,
            "refresh_token": token["refresh_token"],
            "grant_type": "refresh_token",
        }).encode()
        req = urllib.request.Request(
            "https://oauth2.googleapis.com/token",
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with urllib.request.urlopen(req) as resp:
            new = json.loads(resp.read())
        token["access_token"] = new["access_token"]
        token["expires_at"] = datetime.now().timestamp() + new.get("expires_in", 3600)
        with open(GCAL_TOKEN_FILE, "w") as f:
            json.dump(token, f, indent=2)

    return token["access_token"]


def gcal_api(path, method="GET", body=None):
    token = gcal_get_token()
    url = "https://www.googleapis.com/calendar/v3" + path
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + token})
    req.method = method
    if body:
        req.data = json.dumps(body).encode()
        req.add_header("Content-Type", "application/json")
    if method == "DELETE":
        urllib.request.urlopen(req)
        return {"status": "deleted"}
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def list_events(days=7):
    now = datetime.now()
    end = now + timedelta(days=days)
    results = []

    # iCloud calendars
    try:
        principal = caldav.DAVClient(url=ICLOUD_URL, username=ICLOUD_USER, password=ICLOUD_PASS).principal()
        for cal in principal.calendars():
            if cal.name in SKIP_CALENDARS:
                continue
            try:
                events = cal.date_search(start=now, end=end, expand=True)
                for event in events:
                    vevent = event.vobject_instance.vevent
                    summary = str(vevent.summary.value) if hasattr(vevent, "summary") else "No title"
                    dtstart = vevent.dtstart.value
                    dtend = vevent.dtend.value if hasattr(vevent, "dtend") else None
                    location = str(vevent.location.value).replace("\n", ", ") if hasattr(vevent, "location") else None
                    title = summary
                    if location:
                        title += f" @ {location}"
                    results.append({
                        "calendar": cal.name,
                        "source": "iCloud",
                        "title": title,
                        "start": str(dtstart),
                        "end": str(dtend) if dtend else None,
                    })
            except Exception as e:
                results.append({"calendar": cal.name, "source": "iCloud", "error": str(e)})
    except Exception as e:
        print(f"[iCloud] Connection error: {e}")

    # Google calendars
    try:
        cal_list = gcal_api("/users/me/calendarList")
        for gcal in cal_list.get("items", []):
            if gcal["summary"] in SKIP_CALENDARS:
                continue
            if gcal.get("accessRole") not in ("owner", "writer"):
                continue
            cal_id = urllib.parse.quote(gcal["id"], safe="")
            time_min = now.strftime("%Y-%m-%dT%H:%M:%S") + "Z"
            time_max = end.strftime("%Y-%m-%dT%H:%M:%S") + "Z"
            events = gcal_api(
                f"/calendars/{cal_id}/events?timeMin={time_min}&timeMax={time_max}"
                f"&singleEvents=true&orderBy=startTime&maxResults=50"
            )
            for event in events.get("items", []):
                start_val = event.get("start", {}).get("dateTime") or event.get("start", {}).get("date", "")
                end_val = event.get("end", {}).get("dateTime") or event.get("end", {}).get("date", "")
                results.append({
                    "calendar": gcal["summary"],
                    "source": "Google",
                    "title": event.get("summary", "No title"),
                    "start": start_val,
                    "end": end_val,
                })
    except Exception as e:
        print(f"[Google] Error: {e}")

    # ICS feeds
    for feed_name, feed_url in ICS_FEEDS.items():
        try:
            from icalendar import Calendar as iCalendar
            req = urllib.request.Request(feed_url)
            with urllib.request.urlopen(req, timeout=10) as resp:
                cal_data = iCalendar.from_ical(resp.read())
            for component in cal_data.walk():
                if component.name == "VEVENT":
                    dtstart = component.get("dtstart")
                    dtend = component.get("dtend")
                    summary = str(component.get("summary", "No title"))
                    location = str(component.get("location", ""))
                    if dtstart:
                        start_dt = dtstart.dt
                        if hasattr(start_dt, "date"):
                            start_date = start_dt
                        else:
                            start_date = datetime.combine(start_dt, datetime.min.time())
                        if now.date() <= start_date.date() if hasattr(start_date, 'date') else now.date() <= start_date <= end.date():
                            if start_date.date() if hasattr(start_date, 'date') else start_date <= end.date():
                                title = summary
                                if location:
                                    title += f" @ {location}"
                                end_val = str(dtend.dt) if dtend else None
                                results.append({
                                    "calendar": feed_name,
                                    "source": "ICS",
                                    "title": title,
                                    "start": str(start_dt),
                                    "end": end_val,
                                })
        except ImportError:
            # Fallback: parse ICS manually
            try:
                req = urllib.request.Request(feed_url)
                with urllib.request.urlopen(req, timeout=10) as resp:
                    ics_text = resp.read().decode()
                import re
                events_raw = ics_text.split("BEGIN:VEVENT")
                for ev in events_raw[1:]:
                    m_start = re.search(r"DTSTART[^:]*:(\d{8}T\d{6})", ev)
                    m_end = re.search(r"DTEND[^:]*:(\d{8}T\d{6})", ev)
                    m_summary = re.search(r"SUMMARY:(.*?)(?:\r?\n[^ ])", ev, re.DOTALL)
                    m_location = re.search(r"LOCATION:(.*?)(?:\r?\n[^ ])", ev, re.DOTALL)
                    if m_start:
                        s = m_start.group(1)
                        start_dt = datetime.strptime(s, "%Y%m%dT%H%M%S")
                        if now.replace(tzinfo=None) <= start_dt <= end.replace(tzinfo=None) + timedelta(days=1):
                            summary = m_summary.group(1).strip().replace("\r", "") if m_summary else "No title"
                            location = m_location.group(1).strip().replace("\\,", ",").replace("\r", "") if m_location else ""
                            title = summary
                            if location:
                                title += f" @ {location}"
                            end_val = None
                            if m_end:
                                end_val = str(datetime.strptime(m_end.group(1), "%Y%m%dT%H%M%S"))
                            results.append({
                                "calendar": feed_name,
                                "source": "ICS",
                                "title": title,
                                "start": str(start_dt),
                                "end": end_val,
                            })
            except Exception as e:
                print(f"[{feed_name}] ICS fetch error: {e}")
        except Exception as e:
            print(f"[{feed_name}] Error: {e}")

    if not results:
        print(f"No events in the next {days} days.")
    else:
        for r in sorted(results, key=lambda x: x.get("start", "")):
            if "error" in r:
                print(f"[{r['calendar']}] Error: {r['error']}")
            else:
                end_str = f" - {r['end']}" if r.get("end") else ""
                print(f"[{r['calendar']}] {r['start']}{end_str}: {r['title']}")


def add_event(title, start_str, end_str=None, calendar_name=None, location=None):
    cal_name = calendar_name or DEFAULT_CALENDAR
    start = datetime.fromisoformat(start_str)
    end_dt = datetime.fromisoformat(end_str) if end_str else start + timedelta(hours=1)

    # Auto-extract location from title if not provided
    # Handles: "Event @ Venue - 123 Main St" or "Event - 123 Main St, City, ST ZIP"
    if not location:
        import re
        # Pattern: "title - address" where address looks like "123 Street, City"
        addr_match = re.search(r'\s*-\s*(\d+\s+.+?,\s*.+?)$', title)
        if addr_match:
            location = addr_match.group(1).strip()
            title = title[:addr_match.start()].strip()
        # Pattern: "title @ venue" - put venue in location
        elif " @ " in title:
            parts = title.rsplit(" @ ", 1)
            title = parts[0].strip()
            location = parts[1].strip()

    # Build VCALENDAR
    loc_line = f"\nLOCATION:{location}" if location else ""
    vcal = (
        "BEGIN:VCALENDAR\n"
        "VERSION:2.0\n"
        "PRODID:-//Bob//ClusterHAT//EN\n"
        "BEGIN:VEVENT\n"
        f"DTSTART:{start.strftime('%Y%m%dT%H%M%S')}\n"
        f"DTEND:{end_dt.strftime('%Y%m%dT%H%M%S')}\n"
        f"SUMMARY:{title}{loc_line}\n"
        "END:VEVENT\n"
        "END:VCALENDAR"
    )

    # iCloud calendars: Family, Home
    icloud_cals = {"family", "home"}
    if cal_name.lower() in icloud_cals:
        try:
            principal = caldav.DAVClient(url=ICLOUD_URL, username=ICLOUD_USER, password=ICLOUD_PASS).principal()
            target = None
            for cal in principal.calendars():
                if cal.name.lower() == cal_name.lower():
                    target = cal
                    break
            if target:
                target.save_event(vcal)
                loc_msg = f" at {location}" if location else ""
                print(f"Event created: '{title}'{loc_msg} on {start.strftime('%B %d, %Y %I:%M %p')} - {end_dt.strftime('%I:%M %p')} [{cal_name}, iCloud]")
                return
        except Exception as e:
            print(f"[iCloud] Failed to add event: {e}")

    # Google Calendar: Personal and others
    try:
        cal_list = gcal_api("/users/me/calendarList")
        for gcal in cal_list.get("items", []):
            if gcal.get("accessRole") in ("owner", "writer") and gcal["summary"].lower() == cal_name.lower():
                cal_id = urllib.parse.quote(gcal["id"], safe="")
                body = {
                    "summary": title,
                    "start": {"dateTime": start.isoformat(), "timeZone": "America/Los_Angeles"},
                    "end": {"dateTime": end_dt.isoformat(), "timeZone": "America/Los_Angeles"},
                }
                if location:
                    body["location"] = location
                gcal_api(f"/calendars/{cal_id}/events", method="POST", body=body)
                loc_msg = f" at {location}" if location else ""
                print(f"Event created: '{title}'{loc_msg} on {start.strftime('%B %d, %Y %I:%M %p')} - {end_dt.strftime('%I:%M %p')} [{cal_name}, Google]")
                return
    except Exception as e:
        print(f"[Google] Failed to add event: {e}")

    avail = ["Family (iCloud)", "Home (iCloud)", "Personal (Google)"]
    print(f"Calendar '{cal_name}' not found. Available: {', '.join(avail)}")


def search_events(query, days=30):
    now = datetime.now()
    end = now + timedelta(days=days)
    found = []

    # iCloud
    try:
        principal = caldav.DAVClient(url=ICLOUD_URL, username=ICLOUD_USER, password=ICLOUD_PASS).principal()
        for cal in principal.calendars():
            if cal.name in SKIP_CALENDARS:
                continue
            try:
                events = cal.date_search(start=now, end=end, expand=True)
                for event in events:
                    vevent = event.vobject_instance.vevent
                    summary = str(vevent.summary.value) if hasattr(vevent, "summary") else ""
                    location = str(vevent.location.value).replace("\n", ", ") if hasattr(vevent, "location") else ""
                    searchable = summary + " " + location
                    if query.lower() in searchable.lower():
                        title = summary
                        if location:
                            title += f" @ {location}"
                        found.append({
                            "calendar": cal.name,
                            "title": title,
                            "start": str(vevent.dtstart.value),
                        })
            except Exception:
                pass
    except Exception:
        pass

    # Google
    try:
        cal_list = gcal_api("/users/me/calendarList")
        for gcal in cal_list.get("items", []):
            if gcal["summary"] in SKIP_CALENDARS:
                continue
            cal_id = urllib.parse.quote(gcal["id"], safe="")
            time_min = now.strftime("%Y-%m-%dT%H:%M:%S") + "Z"
            time_max = end.strftime("%Y-%m-%dT%H:%M:%S") + "Z"
            events = gcal_api(
                f"/calendars/{cal_id}/events?timeMin={time_min}&timeMax={time_max}"
                f"&singleEvents=true&orderBy=startTime&q={urllib.parse.quote(query)}"
            )
            for event in events.get("items", []):
                found.append({
                    "calendar": gcal["summary"],
                    "title": event.get("summary", "No title"),
                    "start": event.get("start", {}).get("dateTime", event.get("start", {}).get("date", "")),
                })
    except Exception:
        pass

    if not found:
        print(f"No events matching '{query}' in the next {days} days.")
    else:
        for r in found:
            print(f"[{r['calendar']}] {r['start']}: {r['title']}")


def delete_event(query, days=30):
    """Delete an event matching the query. Searches both iCloud and Google calendars."""
    now = datetime.now()
    end = now + timedelta(days=days)
    matches = []

    # iCloud
    try:
        principal = caldav.DAVClient(url=ICLOUD_URL, username=ICLOUD_USER, password=ICLOUD_PASS).principal()
        for cal in principal.calendars():
            if cal.name in SKIP_CALENDARS:
                continue
            try:
                events = cal.date_search(start=now, end=end, expand=False)
                for event in events:
                    vevent = event.vobject_instance.vevent
                    summary = str(vevent.summary.value) if hasattr(vevent, "summary") else ""
                    if query.lower() in summary.lower():
                        matches.append({
                            "source": "iCloud",
                            "calendar": cal.name,
                            "title": summary,
                            "start": str(vevent.dtstart.value),
                            "event_obj": event,
                        })
            except Exception:
                pass
    except Exception as e:
        print(f"[iCloud] Error: {e}")

    # Google
    try:
        cal_list = gcal_api("/users/me/calendarList")
        for gcal_entry in cal_list.get("items", []):
            if gcal_entry["summary"] in SKIP_CALENDARS:
                continue
            if gcal_entry.get("accessRole") not in ("owner", "writer"):
                continue
            cal_id = urllib.parse.quote(gcal_entry["id"], safe="")
            time_min = now.strftime("%Y-%m-%dT%H:%M:%S") + "Z"
            time_max = end.strftime("%Y-%m-%dT%H:%M:%S") + "Z"
            events = gcal_api(
                f"/calendars/{cal_id}/events?timeMin={time_min}&timeMax={time_max}"
                f"&singleEvents=true&orderBy=startTime&q={urllib.parse.quote(query)}"
            )
            for event in events.get("items", []):
                matches.append({
                    "source": "Google",
                    "calendar": gcal_entry["summary"],
                    "title": event.get("summary", "No title"),
                    "start": event.get("start", {}).get("dateTime", event.get("start", {}).get("date", "")),
                    "event_id": event["id"],
                    "cal_id": gcal_entry["id"],
                })
    except Exception as e:
        print(f"[Google] Error: {e}")

    if not matches:
        print(f"No events matching '{query}' found in the next {days} days.")
        return

    if len(matches) > 1:
        print(f"Multiple events match '{query}':")
        for i, m in enumerate(matches):
            print(f"  {i+1}. [{m['calendar']}] {m['start']}: {m['title']}")
        print("Please be more specific.")
        return

    m = matches[0]
    if m["source"] == "iCloud":
        m["event_obj"].delete()
        print(f"Deleted: '{m['title']}' on {m['start']} [{m['calendar']}, iCloud]")
    elif m["source"] == "Google":
        cal_id = urllib.parse.quote(m["cal_id"], safe="")
        event_id = m["event_id"]
        gcal_api(f"/calendars/{cal_id}/events/{event_id}", method="DELETE")
        print(f"Deleted: '{m['title']}' on {m['start']} [{m['calendar']}, Google]")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: calendar-tool.py [list|add|search|delete] ...")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "list":
        days = 7
        if "--days" in sys.argv:
            idx = sys.argv.index("--days")
            days = int(sys.argv[idx + 1])
        list_events(days)

    elif cmd == "add":
        if len(sys.argv) < 4:
            print("Usage: calendar-tool.py add 'title' 'start_iso' ['end_iso'] [--calendar NAME] [--location LOCATION]")
            sys.exit(1)
        title = sys.argv[2]
        start = sys.argv[3]
        end_arg = sys.argv[4] if len(sys.argv) > 4 and not sys.argv[4].startswith("--") else None
        cal = None
        location = None
        if "--calendar" in sys.argv:
            idx = sys.argv.index("--calendar")
            cal = sys.argv[idx + 1]
        if "--location" in sys.argv:
            idx = sys.argv.index("--location")
            location = sys.argv[idx + 1]
        add_event(title, start, end_arg, cal, location)

    elif cmd == "search":
        if len(sys.argv) < 3:
            print("Usage: calendar-tool.py search 'query'")
            sys.exit(1)
        search_events(sys.argv[2])

    elif cmd == "delete":
        if len(sys.argv) < 3:
            print("Usage: calendar-tool.py delete 'query'")
            sys.exit(1)
        delete_event(sys.argv[2])

    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
