#!/usr/bin/env python3
"""
Traffic/directions tool using Google Routes + Places API.
Usage:
  traffic-tool.py "destination"
  traffic-tool.py "origin" "destination"
  traffic-tool.py lookup "place name"
If only destination given, origin defaults to Dublin, CA.
Returns: drive time with traffic, distance, route summary.
"""

import sys
import os
import json
import urllib.request

# Load config
_cfg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
with open(_cfg_path) as _f:
    _cfg = json.load(_f)

API_KEY = _cfg["google_maps"]["api_key"]
DEFAULT_ORIGIN = "Dublin, CA"
ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
PLACES_URL = "https://places.googleapis.com/v1/places:searchText"


def get_directions(origin, destination):
    body = json.dumps({
        "origin": {"address": origin},
        "destination": {"address": destination},
        "travelMode": "DRIVE",
        "routingPreference": "TRAFFIC_AWARE"
    }).encode()

    req = urllib.request.Request(ROUTES_URL, data=body, headers={
        "Content-Type": "application/json",
        "X-Goog-Api-Key": API_KEY,
        "X-Goog-FieldMask": "routes.duration,routes.staticDuration,routes.distanceMeters,routes.description,routes.legs"
    })

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        err = json.loads(e.read())
        print("Error: %s" % err.get("error", {}).get("message", "unknown"))
        return
    except Exception as e:
        print("Error: %s" % e)
        return

    if not data.get("routes"):
        print("No route found")
        return

    route = data["routes"][0]
    duration = route.get("duration", "0s").rstrip("s")
    static_duration = route.get("staticDuration", "0s").rstrip("s")
    distance_m = route.get("distanceMeters", 0)
    description = route.get("description", "")

    duration_min = int(duration) // 60
    static_min = int(static_duration) // 60
    distance_mi = distance_m / 1609.34

    print("From: %s" % origin)
    print("To: %s" % destination)
    print("Distance: %.1f miles" % distance_mi)
    print("Drive time (with traffic): %d min" % duration_min)
    if duration_min != static_min:
        print("Drive time (no traffic): %d min" % static_min)
    if description:
        print("Route: via %s" % description)


def lookup_place(query):
    """Look up a place name and return its address."""
    body = json.dumps({"textQuery": query}).encode()
    req = urllib.request.Request(PLACES_URL, data=body, headers={
        "Content-Type": "application/json",
        "X-Goog-Api-Key": API_KEY,
        "X-Goog-FieldMask": "places.displayName,places.formattedAddress"
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        for p in data.get("places", []):
            name = p.get("displayName", {}).get("text", "")
            addr = p.get("formattedAddress", "")
            print(f"{name}: {addr}")
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    if len(sys.argv) == 2:
        get_directions(DEFAULT_ORIGIN, sys.argv[1])
    elif len(sys.argv) == 3 and sys.argv[1] == "lookup":
        lookup_place(sys.argv[2])
    elif len(sys.argv) == 3:
        get_directions(sys.argv[1], sys.argv[2])
    else:
        print("Usage: traffic-tool.py 'destination' | traffic-tool.py 'origin' 'dest' | traffic-tool.py lookup 'place'")
        sys.exit(1)
