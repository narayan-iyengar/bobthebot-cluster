#!/usr/bin/env python3
"""
Gmail read-only tool for the cluster.
Usage:
  email-tool.py inbox [--count N]           Show recent emails
  email-tool.py search "query"              Search emails
  email-tool.py read <message_id>           Read a specific email
  email-tool.py unread                      Show unread emails
"""

import sys
import json
import os
import urllib.request
import urllib.parse
import urllib.error
import base64
from datetime import datetime

# Load config
_cfg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
with open(_cfg_path) as _f:
    _cfg = json.load(_f)

TOKEN_FILE = _cfg["google"]["token_file"]
CLIENT_ID = _cfg["google"]["client_id"]
CLIENT_SECRET = _cfg["google"]["client_secret"]


def get_token():
    with open(TOKEN_FILE) as f:
        token = json.load(f)

    expires_at = token.get("expires_at", 0)
    if expires_at and datetime.now().timestamp() > expires_at - 60:
        data = urllib.parse.urlencode({
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
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
        with open(TOKEN_FILE, "w") as f:
            json.dump(token, f, indent=2)

    return token["access_token"]


def gmail_api(path):
    token = get_token()
    url = "https://www.googleapis.com/gmail/v1/users/me" + path
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + token})
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def get_header(headers, name):
    for h in headers:
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""


def format_message_summary(msg):
    headers = msg.get("payload", {}).get("headers", [])
    subject = get_header(headers, "Subject") or "(no subject)"
    sender = get_header(headers, "From")
    date = get_header(headers, "Date")
    snippet = msg.get("snippet", "")
    msg_id = msg.get("id", "")
    labels = msg.get("labelIds", [])
    unread = "UNREAD" in labels
    marker = "[NEW] " if unread else ""
    return f"{marker}From: {sender}\nDate: {date}\nSubject: {subject}\nPreview: {snippet}\nID: {msg_id}"


def get_body(msg):
    """Extract plain text body from message."""
    payload = msg.get("payload", {})

    # Simple message
    if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")

    # Multipart message
    for part in payload.get("parts", []):
        if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
            return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")
        # Nested multipart
        for subpart in part.get("parts", []):
            if subpart.get("mimeType") == "text/plain" and subpart.get("body", {}).get("data"):
                return base64.urlsafe_b64decode(subpart["body"]["data"]).decode("utf-8", errors="replace")

    return "(no plain text body found)"


def list_inbox(count=10):
    data = gmail_api(f"/messages?maxResults={count}&labelIds=INBOX")
    messages = data.get("messages", [])
    if not messages:
        print("Inbox is empty.")
        return

    for m in messages:
        msg = gmail_api(f"/messages/{m['id']}?format=metadata&metadataHeaders=From&metadataHeaders=Subject&metadataHeaders=Date")
        print(format_message_summary(msg))
        print()


def list_unread(count=20):
    data = gmail_api(f"/messages?maxResults={count}&labelIds=INBOX&q=is:unread")
    messages = data.get("messages", [])
    if not messages:
        print("No unread emails.")
        return

    print(f"Found {len(messages)} unread email(s):\n")
    for m in messages:
        msg = gmail_api(f"/messages/{m['id']}?format=metadata&metadataHeaders=From&metadataHeaders=Subject&metadataHeaders=Date")
        print(format_message_summary(msg))
        print()


def search_emails(query, count=10):
    data = gmail_api(f"/messages?maxResults={count}&q={urllib.parse.quote(query)}")
    messages = data.get("messages", [])
    if not messages:
        print(f"No emails matching '{query}'.")
        return

    print(f"Found {len(messages)} email(s) matching '{query}':\n")
    for m in messages:
        msg = gmail_api(f"/messages/{m['id']}?format=metadata&metadataHeaders=From&metadataHeaders=Subject&metadataHeaders=Date")
        print(format_message_summary(msg))
        print()


def read_email(message_id):
    try:
        msg = gmail_api(f"/messages/{message_id}?format=full")
        headers = msg.get("payload", {}).get("headers", [])
        subject = get_header(headers, "Subject") or "(no subject)"
        sender = get_header(headers, "From")
        date = get_header(headers, "Date")
        to = get_header(headers, "To")
        body = get_body(msg)

        # Truncate very long emails
        if len(body) > 5000:
            body = body[:5000] + "\n\n[... truncated, email too long ...]"

        print(f"From: {sender}")
        print(f"To: {to}")
        print(f"Date: {date}")
        print(f"Subject: {subject}")
        print(f"\n{body}")
    except urllib.error.HTTPError as e:
        print(f"Error reading email: {e.code}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: email-tool.py [inbox|unread|search|read] ...")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "inbox":
        count = 10
        if "--count" in sys.argv:
            idx = sys.argv.index("--count")
            count = int(sys.argv[idx + 1])
        list_inbox(count)

    elif cmd == "unread":
        list_unread()

    elif cmd == "search":
        if len(sys.argv) < 3:
            print("Usage: email-tool.py search 'query'")
            sys.exit(1)
        search_emails(sys.argv[2])

    elif cmd == "read":
        if len(sys.argv) < 3:
            print("Usage: email-tool.py read <message_id>")
            sys.exit(1)
        read_email(sys.argv[2])

    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
