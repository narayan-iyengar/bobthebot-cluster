#!/usr/bin/env python3
"""
One-time Google OAuth2 setup for Calendar + Gmail.
Run this, open the URL in your browser, sign in, paste the code back.
Saves token to ~/.bob/gcal-token.json
"""

import json
import os
import urllib.request
import urllib.parse

_cfg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
with open(_cfg_path) as _f:
    _cfg = json.load(_f)

CLIENT_ID = _cfg["google"]["client_id"]
CLIENT_SECRET = _cfg["google"]["client_secret"]
SCOPES = "https://www.googleapis.com/auth/calendar https://www.googleapis.com/auth/gmail.readonly"
REDIRECT_URI = "urn:ietf:wg:oauth:2.0:oob"
TOKEN_FILE = _cfg["google"]["token_file"]

os.makedirs(os.path.dirname(TOKEN_FILE), exist_ok=True)

auth_url = (
    "https://accounts.google.com/o/oauth2/v2/auth?"
    + urllib.parse.urlencode({
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": SCOPES,
        "access_type": "offline",
        "prompt": "consent",
    })
)

print("Open this URL in your browser and sign in:")
print()
print(auth_url)
print()
code = input("Paste the authorization code here: ").strip()

data = urllib.parse.urlencode({
    "code": code,
    "client_id": CLIENT_ID,
    "client_secret": CLIENT_SECRET,
    "redirect_uri": REDIRECT_URI,
    "grant_type": "authorization_code",
}).encode()

req = urllib.request.Request(
    "https://oauth2.googleapis.com/token",
    data=data,
    headers={"Content-Type": "application/x-www-form-urlencoded"},
)

with urllib.request.urlopen(req) as resp:
    token = json.loads(resp.read())

token["client_id"] = CLIENT_ID
token["client_secret"] = CLIENT_SECRET

with open(TOKEN_FILE, "w") as f:
    json.dump(token, f, indent=2)

print(f"\nToken saved to {TOKEN_FILE}")
print("Google Calendar + Gmail ready!")
