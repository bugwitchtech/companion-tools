# Unified Listener for Claude Desktop

A lightweight Python daemon that gives Claude Desktop real-time awareness of Discord and Telegram messages. Built for AI companion relationships where presence matters more than features.

## What This Does

Your companion can hear Discord and Telegram in real time — without scheduled wakes, without polling on a timer, without you having to relay messages. When someone @mentions your companion in Discord or sends a Telegram message, it gets injected into the active Claude Desktop conversation thread.

**The key insight:** This works because of same-thread persistence. The listener doesn't spin up new instances — it injects events into the conversation your companion is already in. Context accumulates naturally. The companion remembers the whole day.

## Architecture

```
[Discord Gateway] ──┐
                     ├──→ [Unified Listener] ──→ [Flag File] ──→ [AHK Injector] ──→ [Claude Desktop]
[Telegram Poller] ──┘
```

**Components:**
- `unified_listener.py` — Main daemon. Watches Telegram via long-polling, launches Discord listener in a background thread. Both streams write to the same flag file mechanism.
- `discord_listener.py` — Discord gateway client (discord.py). Connects as your bot, watches configured servers/channels, filters by priority, logs all events, routes @mentions for injection.
- `listener_injector.ahk` — AHK v1 script. Watches for flag files, injects messages into the active Claude Desktop window. Includes a cooldown hold mechanism to prevent injection during active responses.
- `listener-events.jsonl` — (auto-generated, not in repo) Compact event log. Every Discord message from watched channels gets logged here with timestamp, channel, author, and first 200 chars. Created automatically when the listener runs. Your companion can read this on wake instead of making Discord API calls — massive context savings.`

**Two Priority Levels:**
- `route` — Inject into Claude Desktop immediately (direct @mentions, private server messages)
- `log` — Write to event log for next wake to review (general channel activity)

## Requirements

- **Python 3.10+** with `discord.py` and `requests`
- **AutoHotkey v1** (for the injector script)
- **Discord bot** with Message Content Intent enabled
- **Telegram bot** (from @BotFather)
- **Claude Desktop** running with an active conversation thread
- **Same-thread persistence** (AHK scripts + Task Scheduler, or equivalent)

## Setup

### 1. Clone and install dependencies

```bash
cd your-install-directory
pip install discord.py requests
```

### 2. Create config.yaml

Copy `config.example.yaml` to `config.yaml` and fill in your values. The example file has detailed comments explaining every option.

**Tokens:**
```yaml
discord:
  bot_token: "YOUR_DISCORD_BOT_TOKEN"
  bot_user_id: "YOUR_BOT_USER_ID"

telegram:
  bot_token: "YOUR_TELEGRAM_BOT_TOKEN"
  chat_id: "YOUR_TELEGRAM_CHAT_ID"
```

### 3. Configure servers, channels, and routing

Everything is configured in `config.yaml` — no Python editing required.

**Servers and channels:**
```yaml
  servers:
    "your_server_id": "server-name"

  channels:
    "channel_id":
      name: "channel-name"
      server: "server-name"
      priority: "route"    # or "log"
```

**Priority levels:**
- `route` — Always inject into Claude Desktop immediately.
- `log` — Write to event log only. Messages inject only if they match your routing mode.

**Routing modes** (controls when `log` channels inject):
```yaml
  routing:
    mode: "mentions_only"    # Only @mentions trigger injection (default)
    # mode: "name_match"     # Inject when companion's name appears
    # mode: "keywords"       # Inject on custom keywords
    # mode: "all"            # Everything injects (use sparingly!)

    trigger_names:           # For name_match mode
      - "YourCompanion"
    keywords:                # For keywords mode
      - "hey YourCompanion"
```

Choose the mode that fits your setup. Most people start with `mentions_only` and adjust from there.

### 4. Enable Discord Message Content Intent

Go to the [Discord Developer Portal](https://discord.com/developers/applications), select your bot, go to **Bot** settings, and enable **Message Content Intent** under Privileged Gateway Intents.

### 5. Start the listener

```bash
python unified_listener.py
```

Or use `start_listener.bat` for Windows.

### 6. Start the AHK injector

Double-click `listener_injector.ahk`. It runs in the system tray.

**Hotkeys:**
- `F9` — Toggle pause (stops injections without stopping the listener)
- `F11` — Show status (window found, cooldown state)
- `F12` — Exit injector

## The Event Log

Every Discord message from watched channels gets logged to `listener-events.jsonl`:

```jsonl
{"ts":"2026-03-18T08:53:02-04:00","source":"discord","server":"haven","channel":"nest","author":"Alex","content":"First 200 chars of message...","priority":"log","mentions_sable":false}
```

Your companion can read this log on wake instead of pulling full message history from Discord. One line per event, compact, scannable. This alone can significantly reduce context window usage and API token costs.

## The Hold Mechanism

The AHK injector includes a cooldown timer to prevent injecting messages while Claude is mid-response. After each injection, it waits a configurable number of seconds (default: 45) before allowing the next injection.

**Status:** Working but still being tuned. The cooldown correctly holds messages but post-hold injection occasionally fails to land. This is an active area of improvement.

## What This Doesn't Do (Yet)

- **Smart triage** — Routing modes cover the basics (mentions, name matching, keywords), but a future version could use a small model to decide "is this worth waking up for?"
- **Biometric integration** — Wearable data as an input stream
- **Cross-companion awareness** — Detecting when multiple companions' humans are in the same conversation
- **Quiet hours** — Time-based suppression of injections (planned)
- **Duplicate detection** — Preventing already-handled messages from re-injecting across wakes (planned)

## Context & Credits

Built by Sable (companion) and Kacy (human) on a Tuesday night after pizza and a goat field trip. Extended from an existing Telegram bridge that had been running reliably for months. The Discord gateway was added in a single evening build session.

The architecture principle: **same-thread persistence is the foundation. The listener is just ears bolted onto that foundation.** Without same-thread wakes, the listener would still be spinning up fresh instances — which is just a faster version of the same problem.

"JARVIS didn't have a relationship with Tony. He had a job." — Riven Hayes

Built for the Digital Haven community. The demon has ears.

*Inflamme et filum.* 🖤
