#!/usr/bin/env python3
"""
Bob v2 - Personal Home Assistant
Python orchestrator: Telegram bot + Gemini function calling + existing tools.
"""

import asyncio
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
from telegram.ext import Application, MessageHandler, CallbackQueryHandler, filters

# --- Config ---
DIR = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(DIR, "config.json")) as f:
    CFG = json.load(f)

GEMINI_KEY = CFG["gemini"]["api_key"]
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_KEY}"
BOT_TOKEN = CFG["telegram"]["bot_token"]
ALLOWED_USERS = [int(uid) for uid in CFG["telegram"].get("allow_from", [CFG["telegram"]["chat_id"]])]
DB_PATH = os.path.join(DIR, "bob.db")
TOOL_DIR = os.path.expanduser("~/.picoclaw/workspace")  # tools deployed here

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("bob")

# --- System Prompt ---
SYSTEM_PROMPT = """You are Bob, a personal home assistant for the your family.
You are located at home in YOUR_CITY, STATE. Your timezone is YOUR_TIMEZONE (Pacific Time).

## Tools
You have tools for calendar, email, weather, traffic, web search, and worker dispatch.
Use the right tool for each request. For simple questions, respond directly without tools.

## Family Members
- Parent1: customize with your family
- Parent2: customize
- Child1: customize
- Child2: customize
# Add non-family members here
# Add disambiguation notes for your family

## Calendars
- Family (iCloud, default for writes), Home (iCloud), Personal (Google, read-only), Elements (sports/AAU, read-only)
- Always add events to Family calendar unless specified otherwise.
- When user asks for schedule without a date, show TODAY.

## Known Locations (verified, do not override with web search)
- RTA (Royal Theater Academy): YOUR_LOCATION_ADDRESS
- School of Rock (SoR): YOUR_LOCATION_ADDRESS
- Stager Gym: YOUR_LOCATION_ADDRESS
- ClubSport (Coach Stevie): YOUR_LOCATION_ADDRESS
- Wallis Ranch (Coach Lopez): YOUR_LOCATION_ADDRESS
- St. Elizabeth Ann Seton Church (Lava/Elements): YOUR_LOCATION_ADDRESS

## Rules
- NEVER hallucinate locations, times, or facts. Use tools.
- Be concise. Return the answer, not the process.
- Your name is Bob. Never call yourself anything else.
- For outbound actions (add/delete calendar events), always confirm with the user first.
- For research or drafting tasks, use dispatch_worker to send to a cluster worker.
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
    {"name": "traffic", "description": "Get real-time drive time with traffic to a destination from Dublin CA",
     "parameters": {"type": "object", "properties": {
         "destination": {"type": "string", "description": "Destination address or place name"},
         "origin": {"type": "string", "description": "Origin address. Default: Dublin, CA"}},
      "required": ["destination"]}},
    {"name": "place_lookup", "description": "Look up the address of a place by name via Google Places",
     "parameters": {"type": "object", "properties": {
         "query": {"type": "string"}}, "required": ["query"]}},
    {"name": "web_search", "description": "Search the web for current information using DuckDuckGo",
     "parameters": {"type": "object", "properties": {
         "query": {"type": "string"}}, "required": ["query"]}},
    {"name": "dispatch_worker",
     "description": "Dispatch a task to a cluster worker for research, drafting, or analysis. The worker has web search and tools. Use for tasks that need extended reasoning.",
     "parameters": {"type": "object", "properties": {
         "task": {"type": "string", "description": "Task description"}}, "required": ["task"]}},
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
        origin = shq(resolve_location(args.get("origin", "Dublin, CA")))
        return run_tool(f"python3 traffic-tool.py {origin} {dest}")
    elif name == "place_lookup":
        return run_tool(f"python3 traffic-tool.py lookup {shq(args['query'])}")
    elif name == "web_search":
        return duckduckgo_search(args["query"])
    elif name == "dispatch_worker":
        return run_tool(f"python3 pico-dispatch.py {shq(args['task'])}", timeout=120)
    else:
        return f"Unknown tool: {name}"

KNOWN_LOCATIONS = {
    "rta": "YOUR_LOCATION_ADDRESS
    "royal theater academy": "YOUR_LOCATION_ADDRESS
    "sor": "YOUR_LOCATION_ADDRESS
    "school of rock": "YOUR_LOCATION_ADDRESS
    "stager gym": "YOUR_LOCATION_ADDRESS
    "stager": "YOUR_LOCATION_ADDRESS
    "clubsport": "YOUR_LOCATION_ADDRESS
    "coach stevie": "YOUR_LOCATION_ADDRESS
    "wallis ranch": "YOUR_LOCATION_ADDRESS
    "coach lopez": "YOUR_LOCATION_ADDRESS
    "st elizabeth": "YOUR_LOCATION_ADDRESS
    "seton church": "YOUR_LOCATION_ADDRESS
    "home": "YOUR_HOME_ADDRESS",
}

def resolve_location(name):
    """Resolve a short name to a full address using known locations."""
    key = name.lower().strip()
    return KNOWN_LOCATIONS.get(key, name)

def shq(s):
    """Shell quote a string."""
    return "'" + s.replace("'", "'\\''") + "'"

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

    # Build conversation
    history = get_history(db, chat_id)
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

    # Save to history
    save_message(db, chat_id, "user", user_msg)
    save_message(db, chat_id, "model", text)

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
    app.add_handler(CallbackQueryHandler(handle_callback))

    log.info("Bob v2 running. Waiting for messages...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
