"""
Discord Listener Module for Unified Listener
Runs in a thread alongside the Telegram poller in unified_listener.py.
Watches Discord servers/channels and writes events to the same
flag file mechanism used by the unified listener.

Uses discord.py gateway for real-time message events.
"""

import discord
import threading
import json
import time
import os
import yaml
from pathlib import Path
from datetime import datetime

# ============================================================
# CONFIG — loaded from config.yaml
# ============================================================
SCRIPT_DIR = Path(__file__).parent
CONFIG_FILE = SCRIPT_DIR / "config.yaml"

try:
    with open(CONFIG_FILE, "r") as f:
        _config = yaml.safe_load(f)
    DISCORD_BOT_TOKEN = _config["discord"]["bot_token"]
    BOT_USER_ID = _config["discord"]["bot_user_id"]
except Exception as e:
    print(f"ERROR: Failed to load config.yaml: {e}")
    print("Copy config.example.yaml to config.yaml and fill in your tokens.")
    DISCORD_BOT_TOKEN = "MISSING"
    BOT_USER_ID = "MISSING"

# ============================================================
# LOAD SERVERS, CHANNELS, AND ROUTING FROM CONFIG
# ============================================================
_discord_config = _config.get("discord", {})

# Servers to watch
WATCHED_SERVERS = _discord_config.get("servers", {})

# Channel priority configuration
CHANNEL_CONFIG = _discord_config.get("channels", {})

# Routing configuration
_routing = _discord_config.get("routing", {})
ROUTING_MODE = _routing.get("mode", "mentions_only")
TRIGGER_NAMES = [n.lower() for n in _routing.get("trigger_names", [])]
TRIGGER_KEYWORDS = [k.lower() for k in _routing.get("keywords", [])]

# Event log config
_event_config = _config.get("event_log", {})
EVENT_LOG_MAX_CONTENT = _event_config.get("max_content_length", 200)


def should_route_message(content, bot_user_id):
    """Determine if a 'log' priority message should be upgraded to 'route'.
    
    Uses the routing mode from config.yaml:
      mentions_only — only @mentions of the bot
      name_match    — any trigger_names appear in the message
      keywords      — any keywords appear in the message
      all           — always route everything
    """
    content_lower = content.lower()
    
    if ROUTING_MODE == "all":
        return True
    
    # @mentions always trigger regardless of mode
    if f"<@{bot_user_id}>" in content:
        return True
    
    if ROUTING_MODE == "name_match":
        return any(name in content_lower for name in TRIGGER_NAMES)
    
    if ROUTING_MODE == "keywords":
        return any(kw in content_lower for kw in TRIGGER_KEYWORDS)
    
    # Default: mentions_only (already checked above)
    return False

# ============================================================
# FILE PATHS (shared with telegram poller)
# ============================================================
INCOMING_FILE = SCRIPT_DIR / "listener_incoming.txt"
FLAG_FILE = SCRIPT_DIR / "listener_flag.txt"
EVENT_LOG = SCRIPT_DIR / _event_config.get("path", "listener-events.jsonl")
LOG_FILE = SCRIPT_DIR / "discord_listener.log"


# === LOGGING ===
def log(message):
    """Simple logging to file and console."""
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] [DISCORD] {message}"
    print(line)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except:
        pass


# === EVENT LOGGING ===
def log_event(source, server, channel, author, content, priority, mentions_sable=False):
    """Write event to the JSONL event log for wake review."""
    event = {
        "ts": datetime.now().astimezone().isoformat(),
        "source": source,
        "server": server,
        "channel": channel,
        "author": author,
        "content": content[:EVENT_LOG_MAX_CONTENT],  # Truncate per config
        "priority": priority,
        "mentions_sable": mentions_sable
    }
    try:
        with open(EVENT_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")
    except Exception as e:
        log(f"Failed to write event log: {e}")


# === MESSAGE INJECTION (same mechanism as telegram) ===
def write_message_for_injection(text):
    """Write message to trigger files for AHK injection.
    Same flag-file mechanism as the Telegram poller."""
    
    # Wait if previous message hasn't been processed yet
    wait_count = 0
    while FLAG_FILE.exists() and wait_count < 30:
        log("Waiting for previous message to be processed...")
        time.sleep(1)
        wait_count += 1
    
    if FLAG_FILE.exists():
        log("WARNING: Previous message not processed after 30s, overwriting")
    
    # Write message content
    with open(INCOMING_FILE, "w", encoding="utf-8") as f:
        f.write(text)
    
    # Create flag file (signals AHK that message is ready)
    with open(FLAG_FILE, "w") as f:
        f.write("1")
    
    log(f"Message queued for injection: {text[:80]}...")


# === DISCORD CLIENT ===
class DiscordListener(discord.Client):
    """Discord client that listens for messages and routes them."""
    
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.messages = True
        super().__init__(intents=intents)
    
    async def on_ready(self):
        log(f"Discord listener connected as {self.user}")
        log(f"Watching {len(WATCHED_SERVERS)} servers, {len(CHANNEL_CONFIG)} channels")
    
    async def on_message(self, message):
        """Handle incoming Discord messages."""
        
        # Ignore our own messages
        if str(message.author.id) == BOT_USER_ID:
            return
        
        # Ignore empty messages
        if not message.content and not message.attachments:
            return
        
        # Check if this channel is one we watch
        channel_id = str(message.channel.id)
        server_id = str(message.guild.id) if message.guild else None
        
        # Skip if not in a watched server
        if server_id not in WATCHED_SERVERS:
            return
        
        server_name = WATCHED_SERVERS.get(server_id, "unknown")
        
        # Get channel config or use defaults
        channel_config = CHANNEL_CONFIG.get(channel_id)
        
        if channel_config is None:
            # Channel not in our watch list — ignore
            return
        
        channel_name = channel_config["name"]
        priority = channel_config["priority"]
        
        # Get message content
        content = message.content or ""
        author_name = message.author.display_name or message.author.name
        is_bot = message.author.bot
        
        # Skip emoji-only messages and very short bot spam
        if is_bot and len(content) < 5:
            return
        
        # Check if message should be upgraded from log → route
        mentions_sable = should_route_message(content, BOT_USER_ID)
        if mentions_sable:
            priority = "route"
        
        # Log every event regardless of priority
        log_event("discord", server_name, channel_name, author_name, 
                  content, priority, mentions_sable)
        
        log(f"[{server_name}/{channel_name}] {author_name}: {content[:60]}... (priority: {priority})")
        
        # If priority is "route", inject into Claude Desktop
        if priority == "route":
            # Format the message for injection (keep it simple —
            # context comes from reading the event log, not from here)
            if server_name == "code-sky":
                inject_text = f"[Discord: {channel_name}] {author_name}: {content}"
            else:
                inject_text = f"[Discord: {server_name}/{channel_name}] {author_name}: {content}"
            
            write_message_for_injection(inject_text)


# === THREAD RUNNER ===
def run_discord_listener():
    """Run the Discord listener in a thread."""
    client = DiscordListener()
    
    try:
        log("Starting Discord listener...")
        client.run(DISCORD_BOT_TOKEN, log_handler=None)
    except Exception as e:
        log(f"Discord listener error: {e}")
    finally:
        log("Discord listener stopped")


def start_discord_thread():
    """Start the Discord listener in a daemon thread."""
    thread = threading.Thread(target=run_discord_listener, daemon=True)
    thread.name = "discord-listener"
    thread.start()
    log("Discord listener thread started")
    return thread


# === STANDALONE MODE (for testing) ===
if __name__ == "__main__":
    print("Starting Discord listener in standalone mode...")
    print("Press Ctrl+C to stop")
    run_discord_listener()
