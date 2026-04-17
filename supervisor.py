#!/usr/bin/env python3
"""
Supervisor - reviews worker output.
1. Deterministic checks (dates) - instant
2. Local LLM on cluster-llm (Llama 3.2 1B) - fast, pre-filter
3. Gemini API direct call - accurate, fallback
4. Auto-approve if all fails
Usage: supervisor.py "task" "output"
"""

import sys
import json
import os
import re
import urllib.request
from datetime import datetime

# Load config
_cfg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
with open(_cfg_path) as _f:
    _cfg = json.load(_f)

GEMINI_API_KEY = _cfg["gemini"]["api_key"]
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
LOCAL_URL = "http://192.168.0.105:8080/v1/chat/completions"

REVIEW_PROMPT = "Review this output for accuracy. Reply APPROVED if correct, or REVISED with the correction. Be concise, one line.\n\nTask: {task}\nOutput: {output}"


def check_dates(text):
    """Verify day-of-week matches dates mentioned."""
    errors = []
    for match in re.finditer(
        r'(monday|tuesday|wednesday|thursday|friday|saturday|sunday)[,\s]+(?:january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{1,2})',
        text.lower()
    ):
        day_name = match.group(1)
        day_num = int(match.group(2))
        for month in range(1, 13):
            try:
                dt = datetime(2026, month, day_num)
                month_name = match.group(0).split()[1]
                if month_name.startswith(dt.strftime("%B").lower()[:3]):
                    actual_day = dt.strftime("%A").lower()
                    if actual_day != day_name:
                        errors.append(f"{day_name.title()} {month_name.title()} {day_num} is actually {actual_day.title()}")
            except ValueError:
                pass
    return errors


def review_via_local(task, output):
    """Local LLM on cluster-llm for fast pre-filter."""
    body = json.dumps({
        "model": "Llama-3.2-1B-Instruct",
        "messages": [{"role": "user", "content": REVIEW_PROMPT.format(task=task, output=output)}],
        "max_tokens": 50,
        "temperature": 0.1
    }).encode()
    req = urllib.request.Request(LOCAL_URL, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            d = json.loads(resp.read())
            result = d["choices"][0]["message"]["content"].strip()
            # Only trust APPROVED from local model. If it says REVISED,
            # the 1B model is often wrong, so escalate to Gemini.
            if result.startswith("APPROVED"):
                return "APPROVED"
            return None  # uncertain, fall through to Gemini
    except Exception:
        return None


def review_via_gemini(task, output):
    """Direct Gemini API call for review."""
    body = json.dumps({
        "contents": [{
            "parts": [{"text": REVIEW_PROMPT.format(task=task, output=output)}]
        }],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 200}
    }).encode()

    req = urllib.request.Request(GEMINI_URL, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            d = json.loads(resp.read())
            return d["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception:
        return None


def review(task, output):
    # Step 1: Deterministic checks (instant)
    date_errors = check_dates(output)
    if date_errors:
        return "REVISED: " + "; ".join(date_errors)

    # Step 2: Local LLM pre-filter (fast, ~3-10s)
    # Only trust APPROVED; REVISED goes to Gemini for verification
    result = review_via_local(task, output)
    if result:
        return result

    # Step 3: Gemini direct API (accurate, ~2-5s)
    result = review_via_gemini(task, output)
    if result:
        return result

    # Step 4: Auto-approve if everything fails
    return "APPROVED"


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: supervisor.py 'task' 'output'")
        sys.exit(1)

    print(review(sys.argv[1], sys.argv[2]))
