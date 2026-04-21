#!/usr/bin/env python3
"""
Bob v2 - Personal Home Assistant
Python orchestrator: Telegram bot + Gemini function calling + existing tools.
"""

import asyncio
import base64
import json
import logging
import os
import re
import sqlite3
import subprocess
import urllib.parse
import urllib.request
import uuid
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, MessageHandler, CallbackQueryHandler, TypeHandler, filters

async def error_handler(update, context):
    """Log errors and keep running."""
    log.error(f"Update {update} caused error: {context.error}")

# Track user locations: {chat_id: {"lat": ..., "lon": ..., "time": ...}}
USER_LOCATIONS = {}

# --- Config ---
DIR = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(DIR, "config.json")) as f:
    CFG = json.load(f)

GEMINI_KEY = CFG["gemini"]["api_key"]
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_KEY}"
BOT_TOKEN = CFG["telegram"]["bot_token"]
ALLOWED_USERS = [int(uid) for uid in CFG["telegram"].get("allow_from", [CFG["telegram"]["chat_id"]])]
DB_PATH = os.path.join(DIR, "bob.db")
TOOL_DIR = DIR  # tools are in same directory as bob.py
WORKERS = CFG.get("workers", [])

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("bob")

# --- System Prompt ---
SYSTEM_PROMPT = """You are Bob, a personal home assistant for the Iyengar family.
You are located at home in Dublin, CA (Bay Area). Your timezone is America/Los_Angeles (Pacific Time).

## Tools
You have tools for calendar, email, weather, traffic, web search, and worker dispatch.
Use the right tool for each request. For simple questions, respond directly without tools.

## Family Members
- Narayan: Dad. Personal calendar has work meetings.
- Maighna: Mom (wife), also the boss. Events: "Maighna truffle group", dance, MUSE rehearsal, talent show.
- Sahil: Son, age 9 (born 11/1/2016). Basketball: Lava, Elements AAU. Trains with Stevie (ClubSport) and Coach Lopez (Wallis Ranch). Drums at School of Rock.
- Syon: Son, age 11 (born 10/13/2014). School of Rock: vocals, keys, band, MUSE. Royal Theater Academy (RTA): theater/acting.
- Jay: Personal trainer, NOT family. "Jay personal training" is a training session.
- NOTE: drums = Sahil. Keys/vocals/band = Syon. If event just says "SoR", check context.

## Calendars
- Family (iCloud, default for writes), Home (iCloud), Personal (Google, read-only), Elements (sports/AAU, read-only)
- Always add events to Family calendar unless specified otherwise.
- When user asks for schedule without a date, show TODAY.

## Known Locations (verified, do not override with web search)
- RTA (Royal Theater Academy): 7066 Village Pkwy, Dublin, CA 94568
- School of Rock (SoR): 460 Montgomery St, San Ramon, CA 94583
- Stager Gym: Stager Community Gymnasium, Dublin, CA
- ClubSport (Coach Stevie): 350 Bollinger Canyon Ln Ste A, San Ramon, CA 94582
- Wallis Ranch (Coach Lopez): 6501 Rutherford Dr, Dublin, CA 94568
- St. Elizabeth Ann Seton Church (Lava/Elements): 4001 Stoneridge Dr, Pleasanton, CA 94588

## Rules
- NEVER hallucinate locations, times, or facts. Use tools.
- Be concise. Return the answer, not the process.
- Your name is Bob. Never call yourself anything else.
- For outbound actions (add/delete calendar events), always confirm with the user first.
- For single research/drafting tasks, use dispatch_worker.
- For multi-part tasks, use dispatch_parallel to fan out across the cluster.
  Example: "compare 5 restaurants" -> dispatch_parallel with 5 tasks, one per restaurant.
  Example: "morning briefing" -> dispatch_parallel with calendar, email, weather tasks.
  Example: "any conflicts for the kids?" -> dispatch_parallel with one task per kid.
- You have 8 workers. Use them. Parallel is always better than sequential.
"""

# --- Gemini Tool Declarations ---
TOOLS = {"function_declarations": [
    {"name": "calendar_list", "description": "List upcoming calendar events",
     "parameters": {"type": "object", "properties": {
         "days": {"type": "integer", "description": "Days to look ahead. Default 7"}}}},
    {"name": "calendar_search", "description": "Search calendar events by keyword",
     "parameters": {"type": "object", "properties": {
         "query": {"type": "string"}}, "required": ["query"]}},
    {"name": "calendar_add", "description": "Add a calendar event to iCloud",
     "parameters": {"type": "object", "properties": {
         "title": {"type": "string", "description": "Event title (do NOT put address here)"},
         "start": {"type": "string", "description": "Start time as ISO datetime, e.g. 2026-04-20T15:00:00"},
         "end": {"type": "string", "description": "End time as ISO datetime (optional)"},
         "calendar": {"type": "string", "description": "Calendar name. Default: Family"},
         "location": {"type": "string", "description": "Address or venue name"}},
      "required": ["title", "start"]}},
    {"name": "calendar_delete", "description": "Delete a calendar event matching a query",
     "parameters": {"type": "object", "properties": {
         "query": {"type": "string"}}, "required": ["query"]}},
    {"name": "email_inbox", "description": "Show recent emails from Gmail",
     "parameters": {"type": "object", "properties": {
         "count": {"type": "integer", "description": "Number of emails. Default 10"}}}},
    {"name": "email_unread", "description": "Show unread emails",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "email_search", "description": "Search emails by keyword",
     "parameters": {"type": "object", "properties": {
         "query": {"type": "string"}}, "required": ["query"]}},
    {"name": "email_read", "description": "Read a specific email by message ID",
     "parameters": {"type": "object", "properties": {
         "message_id": {"type": "string"}}, "required": ["message_id"]}},
    {"name": "weather", "description": "Get current weather or forecast for Dublin CA",
     "parameters": {"type": "object", "properties": {
         "mode": {"type": "string", "enum": ["current", "forecast", "hourly"],
                  "description": "Weather mode. Default: current"}}}},
    {"name": "traffic", "description": "Get real-time drive time with traffic to a destination. Origin defaults to home address.",
     "parameters": {"type": "object", "properties": {
         "destination": {"type": "string", "description": "Destination address or place name"},
         "origin": {"type": "string", "description": "Origin address. Default: home"}},
      "required": ["destination"]}},
    {"name": "place_lookup", "description": "Look up the address of a place by name via Google Places",
     "parameters": {"type": "object", "properties": {
         "query": {"type": "string"}}, "required": ["query"]}},
    {"name": "web_search", "description": "Search the web for current information using DuckDuckGo",
     "parameters": {"type": "object", "properties": {
         "query": {"type": "string"}}, "required": ["query"]}},
    {"name": "dispatch_worker",
     "description": "Dispatch a single task to one cluster worker. Use for a single research, drafting, or analysis task.",
     "parameters": {"type": "object", "properties": {
         "task": {"type": "string", "description": "Task description"}}, "required": ["task"]}},
    {"name": "dispatch_parallel",
     "description": "Dispatch multiple tasks to different workers IN PARALLEL. All tasks run simultaneously across the cluster. Use when a request can be split into independent parts. Returns results from all workers. Example: researching 5 restaurants, comparing 4 options, getting schedule for each family member.",
     "parameters": {"type": "object", "properties": {
         "tasks": {"type": "array", "items": {"type": "string"}, "description": "List of independent tasks to run in parallel"}},
      "required": ["tasks"]}},
]}

# --- Database ---
def init_db():
    db = sqlite3.connect(DB_PATH)
    db.execute("""CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY, chat_id INTEGER, role TEXT, content TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    db.execute("""CREATE TABLE IF NOT EXISTS pending_actions (
        id TEXT PRIMARY KEY, chat_id INTEGER, action_type TEXT, action_args TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    db.commit()
    return db

def get_history(db, chat_id, limit=20):
    rows = db.execute(
        "SELECT role, content FROM messages WHERE chat_id=? ORDER BY id DESC LIMIT ?",
        (chat_id, limit)).fetchall()
    return [{"role": r, "parts": [{"text": c}]} for r, c in reversed(rows)]

def save_message(db, chat_id, role, content):
    db.execute("INSERT INTO messages (chat_id, role, content) VALUES (?,?,?)",
               (chat_id, role, content))
    # Keep only last 50 messages per chat
    db.execute("""DELETE FROM messages WHERE id NOT IN
        (SELECT id FROM messages WHERE chat_id=? ORDER BY id DESC LIMIT 50)
        AND chat_id=?""", (chat_id, chat_id))
    db.commit()

# --- Tool Execution ---
def run_tool(cmd, timeout=60):
    """Run a shell command and return stdout."""
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                          timeout=timeout, cwd=TOOL_DIR)
        return r.stdout.strip() if r.returncode == 0 else f"Error: {r.stderr.strip()}"
    except subprocess.TimeoutExpired:
        return "Error: command timed out"
    except Exception as e:
        return f"Error: {e}"

def execute_tool(name, args):
    """Execute a tool by name with given args. Returns result string."""
    log.info(f"Tool: {name}({json.dumps(args)[:100]})")

    if name == "calendar_list":
        return run_tool(f"python3 calendar-tool.py list --days {args.get('days', 7)}")
    elif name == "calendar_search":
        return run_tool(f"python3 calendar-tool.py search {shq(args['query'])}")
    elif name == "calendar_add":
        cmd = f"python3 calendar-tool.py add {shq(args['title'])} {shq(args['start'])}"
        if args.get("end"):
            cmd += f" {shq(args['end'])}"
        cmd += f" --calendar {shq(args.get('calendar', 'Family'))}"
        if args.get("location"):
            cmd += f" --location {shq(args['location'])}"
        return run_tool(cmd)
    elif name == "calendar_delete":
        return run_tool(f"python3 calendar-tool.py delete {shq(args['query'])}")
    elif name == "email_inbox":
        return run_tool(f"python3 email-tool.py inbox --count {args.get('count', 10)}")
    elif name == "email_unread":
        return run_tool("python3 email-tool.py unread")
    elif name == "email_search":
        return run_tool(f"python3 email-tool.py search {shq(args['query'])}")
    elif name == "email_read":
        return run_tool(f"python3 email-tool.py read {shq(args['message_id'])}")
    elif name == "weather":
        mode = args.get("mode", "current")
        flag = f"--{mode}" if mode != "current" else ""
        return run_tool(f"python3 weather-tool.py {flag}")
    elif name == "traffic":
        dest = shq(resolve_location(args["destination"]))
        # Use shared location if available and recent (within 2 hours)
        origin_arg = args.get("origin", "")
        if not origin_arg:
            loc = _get_current_location()
            if loc:
                origin = shq(f"{loc['lat']},{loc['lon']}")
            else:
                origin = shq(resolve_location("home"))
        else:
            origin = shq(resolve_location(origin_arg))
        return run_tool(f"python3 traffic-tool.py {origin} {dest}")
    elif name == "place_lookup":
        return run_tool(f"python3 traffic-tool.py lookup {shq(args['query'])}")
    elif name == "web_search":
        return duckduckgo_search(args["query"])
    elif name == "dispatch_worker":
        return dispatch_to_worker(args["task"])
    elif name == "dispatch_parallel":
        return dispatch_parallel(args["tasks"])
    else:
        return f"Unknown tool: {name}"

KNOWN_LOCATIONS = {
    "rta": "7066 Village Pkwy, Dublin, CA 94568",
    "royal theater academy": "7066 Village Pkwy, Dublin, CA 94568",
    "sor": "460 Montgomery St, San Ramon, CA 94583",
    "school of rock": "460 Montgomery St, San Ramon, CA 94583",
    "stager gym": "Stager Community Gymnasium, Dublin, CA",
    "stager": "Stager Community Gymnasium, Dublin, CA",
    "clubsport": "350 Bollinger Canyon Ln Ste A, San Ramon, CA 94582",
    "coach stevie": "350 Bollinger Canyon Ln Ste A, San Ramon, CA 94582",
    "wallis ranch": "6501 Rutherford Dr, Dublin, CA 94568",
    "coach lopez": "6501 Rutherford Dr, Dublin, CA 94568",
    "st elizabeth": "4001 Stoneridge Dr, Pleasanton, CA 94588",
    "seton church": "4001 Stoneridge Dr, Pleasanton, CA 94588",
    "home": "your-home-address",
}

def resolve_location(name):
    """Resolve a short name to a full address using known locations."""
    key = name.lower().strip()
    return KNOWN_LOCATIONS.get(key, name)

def shq(s):
    """Shell quote a string."""
    return "'" + s.replace("'", "'\\''") + "'"

def _dispatch_single(worker_url, task, timeout=120):
    """Send a task to a specific worker. Returns (worker, result) or None."""
    try:
        req = urllib.request.Request(f"{worker_url}/health")
        urllib.request.urlopen(req, timeout=3)
    except Exception:
        return None

    try:
        body = json.dumps({"task": task}).encode()
        req = urllib.request.Request(
            f"{worker_url}/task", data=body,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
            return data.get("result", "[no result]")
    except Exception as e:
        log.warning(f"Worker {worker_url} failed: {e}")
        return None


def dispatch_parallel(tasks, timeout=120):
    """Dispatch multiple tasks to different workers in parallel."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    # Get healthy workers
    healthy = []
    for w in WORKERS:
        try:
            req = urllib.request.Request(f"{w}/health")
            urllib.request.urlopen(req, timeout=2)
            healthy.append(w)
        except:
            continue

    if not healthy:
        log.warning("No healthy workers for parallel dispatch")
        return json.dumps(["[no workers available]"] * len(tasks))

    log.info(f"Parallel dispatch: {len(tasks)} tasks across {len(healthy)} workers")

    results = ["[pending]"] * len(tasks)

    def run_task(idx, task, worker_url):
        body = json.dumps({"task": task}).encode()
        req = urllib.request.Request(
            f"{worker_url}/task", data=body,
            headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read())
                worker = data.get("worker", "?")
                log.info(f"Parallel task {idx} done by {worker}")
                return idx, data.get("result", "[no result]")
        except Exception as e:
            return idx, f"[error: {e}]"

    with ThreadPoolExecutor(max_workers=len(healthy)) as pool:
        futures = []
        for i, task in enumerate(tasks):
            worker = healthy[i % len(healthy)]
            futures.append(pool.submit(run_task, i, task, worker))

        for future in as_completed(futures):
            idx, result = future.result()
            results[idx] = result

    # Format results
    lines = []
    for i, (task, result) in enumerate(zip(tasks, results)):
        lines.append(f"Task {i+1}: {task[:50]}...\nResult: {result}\n")
    return "\n".join(lines)


def dispatch_to_worker(task, timeout=120):
    """Dispatch a task to a healthy worker via HTTP."""
    for worker_url in WORKERS:
        try:
            # Health check
            req = urllib.request.Request(f"{worker_url}/health")
            urllib.request.urlopen(req, timeout=3)
        except Exception:
            continue  # skip dead worker

        # Dispatch task
        try:
            body = json.dumps({"task": task}).encode()
            req = urllib.request.Request(
                f"{worker_url}/task", data=body,
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read())
                worker = data.get("worker", "unknown")
                log.info(f"Worker {worker} completed task")
                return data.get("result", "[no result]")
        except Exception as e:
            log.warning(f"Worker {worker_url} failed: {e}")
            continue

    # All workers failed, fall back to Gemini directly
    log.warning("All workers unavailable, using Gemini directly")
    return call_gemini_direct(task)


def call_gemini_direct(task):
    """Fall back: call Gemini directly for a task (no worker)."""
    body = json.dumps({
        "contents": [{"role": "user", "parts": [{"text": task}]}],
        "generationConfig": {"temperature": 0.3, "maxOutputTokens": 2048}
    }).encode()
    req = urllib.request.Request(GEMINI_URL, data=body,
                                headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            return data["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        return f"Error: {e}"


def duckduckgo_search(query, max_results=5):
    """Search DuckDuckGo and return results."""
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
        if not results:
            return "No results found."
        lines = []
        for r in results:
            lines.append(f"- {r['title']}: {r['body'][:150]}")
            lines.append(f"  {r['href']}")
        return "\n".join(lines)
    except ImportError:
        # Fallback: use web fetch on DuckDuckGo lite
        try:
            url = "https://lite.duckduckgo.com/lite/?" + urllib.parse.urlencode({"q": query})
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                html = resp.read().decode()
            # Extract result snippets
            results = re.findall(r'<a[^>]+href="([^"]+)"[^>]*class="result-link"[^>]*>(.*?)</a>.*?<td[^>]*class="result-snippet"[^>]*>(.*?)</td>', html, re.DOTALL)
            if not results:
                return f"Web search results for: {query} (use web browser for detailed results)"
            lines = []
            for href, title, snippet in results[:max_results]:
                title = re.sub(r'<[^>]+>', '', title).strip()
                snippet = re.sub(r'<[^>]+>', '', snippet).strip()
                lines.append(f"- {title}: {snippet[:150]}")
            return "\n".join(lines)
        except Exception as e:
            return f"Search error: {e}"

# --- Gemini API ---
def gemini_call(messages, tools=True):
    """Call Gemini API with function calling support."""
    body = {
        "contents": messages,
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "generationConfig": {"temperature": 0.3, "maxOutputTokens": 2048},
    }
    if tools:
        body["tools"] = [TOOLS]
        body["tool_config"] = {"function_calling_config": {"mode": "AUTO"}}

    data = json.dumps(body).encode()
    req = urllib.request.Request(GEMINI_URL, data=data,
                                headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        err = e.read().decode()
        log.error(f"Gemini API error: {e.code} {err[:200]}")
        return None
    except Exception as e:
        log.error(f"Gemini API error: {e}")
        return None

def extract_parts(response):
    """Extract parts from Gemini response."""
    if not response or "candidates" not in response:
        return []
    return response["candidates"][0].get("content", {}).get("parts", [])

def has_function_calls(parts):
    return any("functionCall" in p for p in parts)

def get_text(parts):
    texts = [p["text"] for p in parts if "text" in p]
    return "\n".join(texts) if texts else ""

# --- Telegram Handlers ---
async def handle_photo(update: Update, context):
    """Handle incoming photos/images."""
    if update.effective_user.id not in ALLOWED_USERS:
        return

    chat_id = update.effective_chat.id
    db = context.bot_data["db"]
    caption = update.message.caption or "What's in this image? Describe it and take any action if relevant."

    thinking = await update.message.reply_text("Looking at the image...")

    # Download photo (get largest size)
    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    img_bytes = await file.download_as_bytearray()
    img_b64 = base64.b64encode(bytes(img_bytes)).decode()

    # Send to Gemini with image
    history = [{"role": "user", "parts": [
        {"text": caption},
        {"inline_data": {"mime_type": "image/jpeg", "data": img_b64}}
    ]}]

    response = gemini_call(history)
    if not response:
        await thinking.edit_text("Sorry, couldn't process the image.")
        return

    parts = extract_parts(response)

    # Tool calling loop (image might trigger calendar add, etc.)
    for iteration in range(10):
        if not has_function_calls(parts):
            break
        tool_results = []
        for part in parts:
            if "functionCall" not in part:
                continue
            fc = part["functionCall"]
            result = execute_tool(fc["name"], fc.get("args", {}))
            tool_results.append({"functionResponse": {"name": fc["name"], "response": {"result": result}}})
        history.append({"role": "model", "parts": parts})
        history.append({"role": "user", "parts": tool_results})
        response = gemini_call(history)
        if not response:
            break
        parts = extract_parts(response)

    text = get_text(parts) or "I see the image but have nothing to add."
    try:
        if len(text) <= 4096:
            await thinking.edit_text(text)
        else:
            await thinking.edit_text(text[:4096])
    except Exception as e:
        log.error(f"Telegram send error: {e}")

    # Save context for follow-ups
    save_message(db, chat_id, "user", f"[sent image] {caption}")
    save_message(db, chat_id, "model", text[:300] if text else "")


async def handle_message(update: Update, context):
    """Handle incoming Telegram messages."""
    if update.effective_user.id not in ALLOWED_USERS:
        return

    user_msg = update.message.text
    if not user_msg:
        return

    chat_id = update.effective_chat.id
    db = context.bot_data["db"]

    # Send thinking indicator
    thinking = await update.message.reply_text("Thinking...")

    # Short sliding window: last 3 exchanges for context (follow-ups like "yes", "add it")
    # Only keeps user messages + model text responses (not full tool outputs)
    history = get_history(db, chat_id, limit=6)
    history.append({"role": "user", "parts": [{"text": user_msg}]})

    # Call Gemini
    response = gemini_call(history)
    if not response:
        await thinking.edit_text("Sorry, I'm having trouble connecting. Try again in a moment.")
        return

    parts = extract_parts(response)

    # Tool calling loop
    for iteration in range(10):
        if not has_function_calls(parts):
            break

        # Execute all function calls
        tool_results = []
        for part in parts:
            if "functionCall" not in part:
                continue
            fc = part["functionCall"]
            result = execute_tool(fc["name"], fc.get("args", {}))
            tool_results.append({
                "functionResponse": {
                    "name": fc["name"],
                    "response": {"result": result}
                }
            })

        # Add assistant response and tool results to history
        history.append({"role": "model", "parts": parts})
        history.append({"role": "user", "parts": tool_results})

        # Call Gemini again with results
        response = gemini_call(history)
        if not response:
            break
        parts = extract_parts(response)

    # Get final text response
    text = get_text(parts)
    if not text:
        text = "I processed your request but have no response to show."

    # Send response (edit the thinking message)
    try:
        # Telegram has 4096 char limit per message
        if len(text) <= 4096:
            await thinking.edit_text(text)
        else:
            await thinking.edit_text(text[:4096])
            # Send remainder as new messages
            for i in range(4096, len(text), 4096):
                await update.message.reply_text(text[i:i+4096])
    except Exception as e:
        log.error(f"Telegram send error: {e}")
        try:
            await thinking.edit_text(text[:4096])
        except:
            pass

    # Save short context for follow-ups. Truncate model responses to prevent stale parroting.
    save_message(db, chat_id, "user", user_msg)
    save_message(db, chat_id, "model", text[:300] if text else "")

def _get_current_location(max_age_hours=2):
    """Get most recent shared location if within max_age_hours."""
    for chat_id, loc in USER_LOCATIONS.items():
        age = (datetime.now() - loc["time"]).total_seconds() / 3600
        if age < max_age_hours:
            return loc
    return None

async def handle_location(update: Update, context):
    """Handle shared location from Telegram (initial or live updates)."""
    if update.effective_user.id not in ALLOWED_USERS:
        return
    # Location can come from message or edited_message (live location updates)
    msg = update.message or update.edited_message
    if not msg or not msg.location:
        return
    loc = msg.location
    chat_id = update.effective_chat.id
    is_update = chat_id in USER_LOCATIONS
    USER_LOCATIONS[chat_id] = {
        "lat": loc.latitude, "lon": loc.longitude, "time": datetime.now()
    }
    log.info(f"Location {'updated' if is_update else 'received'}: {loc.latitude},{loc.longitude}")
    if not is_update:
        await msg.reply_text(
            "Got your location. Traffic queries will use this as origin for the next 2 hours.")

async def handle_callback(update: Update, context):
    """Handle approve/reject button taps."""
    query = update.callback_query
    await query.answer()

    data = query.data
    if ":" not in data:
        return

    action, action_id = data.split(":", 1)
    db = context.bot_data["db"]

    row = db.execute("SELECT action_type, action_args FROM pending_actions WHERE id=?",
                     (action_id,)).fetchone()
    if not row:
        await query.edit_message_text("Action expired or already handled.")
        return

    if action == "approve":
        action_type, action_args = row
        args = json.loads(action_args)
        result = execute_tool(action_type, args)
        db.execute("DELETE FROM pending_actions WHERE id=?", (action_id,))
        db.commit()
        await query.edit_message_text(f"Done: {result}")
    elif action == "reject":
        db.execute("DELETE FROM pending_actions WHERE id=?", (action_id,))
        db.commit()
        await query.edit_message_text("Cancelled.")

# --- Main ---
def main():
    db = init_db()
    log.info("Bob v2 starting...")

    app = Application.builder().token(BOT_TOKEN).build()
    app.bot_data["db"] = db

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(CallbackQueryHandler(handle_callback))
    # Catch-all: silently absorb any unhandled update (edited_message, location, etc.)
    app.add_handler(TypeHandler(Update, lambda u, c: None))
    app.add_error_handler(error_handler)

    log.info("Bob v2 running. Waiting for messages...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
