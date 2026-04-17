#!/usr/bin/env python3
"""
Weather tool using Open-Meteo (free, no API key).
Usage:
  weather-tool.py              Today's weather for Dublin, CA
  weather-tool.py --forecast   3-day forecast for Dublin, CA
  weather-tool.py --hourly     Hourly forecast for today
"""

import sys
import json
import urllib.request
from datetime import datetime

# Dublin, CA coordinates
LAT = 37.7022
LON = -121.9358

WMO_CODES = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Foggy", 48: "Depositing rime fog",
    51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
    61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
    71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow",
    80: "Slight rain showers", 81: "Moderate rain showers", 82: "Violent rain showers",
    95: "Thunderstorm", 96: "Thunderstorm with slight hail", 99: "Thunderstorm with heavy hail"
}


def fetch(url):
    with urllib.request.urlopen(url, timeout=10) as resp:
        return json.loads(resp.read())


def current_weather():
    url = (
        f"https://api.open-meteo.com/v1/forecast?"
        f"latitude={LAT}&longitude={LON}"
        f"&current=temperature_2m,relative_humidity_2m,apparent_temperature,"
        f"weather_code,wind_speed_10m,wind_gusts_10m"
        f"&temperature_unit=fahrenheit&wind_speed_unit=mph"
        f"&timezone=America/Los_Angeles"
    )
    data = fetch(url)
    c = data["current"]
    code = c.get("weather_code", 0)
    condition = WMO_CODES.get(code, f"Code {code}")

    print(f"Dublin, CA - {datetime.now().strftime('%A %B %d, %I:%M %p')}")
    print(f"Condition: {condition}")
    print(f"Temperature: {c['temperature_2m']}F (feels like {c['apparent_temperature']}F)")
    print(f"Humidity: {c['relative_humidity_2m']}%")
    print(f"Wind: {c['wind_speed_10m']} mph (gusts {c['wind_gusts_10m']} mph)")


def forecast():
    url = (
        f"https://api.open-meteo.com/v1/forecast?"
        f"latitude={LAT}&longitude={LON}"
        f"&daily=weather_code,temperature_2m_max,temperature_2m_min,"
        f"precipitation_probability_max,wind_speed_10m_max"
        f"&temperature_unit=fahrenheit&wind_speed_unit=mph"
        f"&timezone=America/Los_Angeles&forecast_days=3"
    )
    data = fetch(url)
    d = data["daily"]

    print("Dublin, CA - 3 Day Forecast")
    for i in range(len(d["time"])):
        date = d["time"][i]
        code = d["weather_code"][i]
        condition = WMO_CODES.get(code, f"Code {code}")
        hi = d["temperature_2m_max"][i]
        lo = d["temperature_2m_min"][i]
        rain = d["precipitation_probability_max"][i]
        wind = d["wind_speed_10m_max"][i]
        print(f"  {date}: {condition}, {lo}F-{hi}F, {rain}% rain, wind {wind} mph")


def hourly():
    url = (
        f"https://api.open-meteo.com/v1/forecast?"
        f"latitude={LAT}&longitude={LON}"
        f"&hourly=temperature_2m,weather_code,precipitation_probability"
        f"&temperature_unit=fahrenheit"
        f"&timezone=America/Los_Angeles&forecast_days=1"
    )
    data = fetch(url)
    h = data["hourly"]

    print("Dublin, CA - Hourly Today")
    now = datetime.now().hour
    for i in range(now, min(now + 12, len(h["time"]))):
        t = h["time"][i].split("T")[1]
        temp = h["temperature_2m"][i]
        code = h["weather_code"][i]
        condition = WMO_CODES.get(code, f"Code {code}")
        rain = h["precipitation_probability"][i]
        print(f"  {t}: {temp}F, {condition}, {rain}% rain")


if __name__ == "__main__":
    try:
        if "--forecast" in sys.argv:
            forecast()
        elif "--hourly" in sys.argv:
            hourly()
        else:
            current_weather()
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
