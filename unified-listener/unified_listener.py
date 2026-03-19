"""
Unified Listener for Claude Desktop
Watches Telegram and Discord for incoming messages and routes them
to the active Claude Desktop thread via flag files and AHK injection.

Supports: Text messages, photos, images sent as files, voice notes (with transcription),
and real-time Discord gateway events.

SETUP:
1. Edit the CONFIG section below with your bot tokens and chat ID.
2. For voice note transcription, install openai-whisper: pip install openai-whisper
3. For Discord: pip install discord.py

Run with: start_listener.bat (recommended)
Or: python unified_listener.py (visible console for debugging)
"""

import requests
import json
import time
import os
import sys
import yaml
from pathlib import Path
from datetime import datetime

# Import Discord listener for unified operation
try:
    from discord_listener import start_discord_thread, log as discord_log
    DISCORD_AVAILABLE = True
except ImportError:
    DISCORD_AVAILABLE = False

# ============================================================
# CONFIG — loaded from config.yaml
# ============================================================
SCRIPT_DIR = Path(__file__).parent
CONFIG_FILE = SCRIPT_DIR / "config.yaml"

try:
    with open(CONFIG_FILE, "r") as f:
        _config = yaml.safe_load(f)
    BOT_TOKEN = _config["telegram"]["bot_token"]
    CHAT_ID = _config["telegram"]["chat_id"]
except Exception as e:
    print(f"ERROR: Failed to load config.yaml: {e}")
    print("Copy config.example.yaml to config.yaml and fill in your tokens.")
    BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"
    CHAT_ID = "YOUR_CHAT_ID_HERE"
# ============================================================

POLL_TIMEOUT = 30
RETRY_DELAY = 5

# API URLs
API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"
FILE_API_BASE = f"https://api.telegram.org/file/bot{BOT_TOKEN}"

# File paths (same directory as script)
STATE_FILE = SCRIPT_DIR / "telegram_state.json"
INCOMING_FILE = SCRIPT_DIR / "listener_incoming.txt"
FLAG_FILE = SCRIPT_DIR / "listener_flag.txt"
LOG_FILE = SCRIPT_DIR / "poller.log"
PAUSE_FILE = SCRIPT_DIR / "pause.txt"  # Create this file to pause polling

# Photos directory
PHOTOS_DIR = Path(os.path.expanduser("~")) / "TelegramPhotos"
PHOTOS_DIR.mkdir(exist_ok=True)

# Voice notes directory
VOICE_DIR = Path(os.path.expanduser("~")) / "TelegramVoice"
VOICE_DIR.mkdir(exist_ok=True)

# Whisper for voice transcription (lazy load to speed up startup)
whisper_model = None

def get_whisper_model():
    """Lazy load Whisper model on first use."""
    global whisper_model
    if whisper_model is None:
        log("Loading Whisper model (first time may take a moment)...")
        import whisper
        # Using "base" model - good balance of speed and accuracy
        # Options: tiny, base, small, medium, large
        whisper_model = whisper.load_model("base")
        log("Whisper model loaded!")
    return whisper_model

# === LOGGING ===
def log(message):
    """Simple logging to file and console."""
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {message}"
    print(line)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except:
        pass

# === STATE MANAGEMENT ===
def load_state():
    """Load last offset from state file."""
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, "r") as f:
                data = json.load(f)
                return data.get("offset", 0)
        except:
            pass
    return 0

def save_state(offset):
    """Save current offset to state file."""
    with open(STATE_FILE, "w") as f:
        json.dump({"offset": offset}, f)

# === TELEGRAM API ===
def download_photo(file_id, original_filename=None):
    """Download a photo/image from Telegram and return the local path."""
    try:
        # Get file info from Telegram
        result = requests.post(f"{API_BASE}/getFile", json={"file_id": file_id}, timeout=30).json()
        if not result.get("ok"):
            log(f"Failed to get file info: {result}")
            return None

        file_path = result.get("result", {}).get("file_path")
        if not file_path:
            log("No file_path in response")
            return None

        # Download the file
        download_url = f"{FILE_API_BASE}/{file_path}"
        response = requests.get(download_url, timeout=60)

        if response.status_code != 200:
            log(f"Download failed with status {response.status_code}")
            return None

        # Save with timestamp to avoid overwrites
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        if original_filename:
            local_filename = f"{timestamp}_{original_filename}"
        else:
            ext = Path(file_path).suffix or ".jpg"
            local_filename = f"photo_{timestamp}{ext}"

        local_path = PHOTOS_DIR / local_filename

        with open(local_path, "wb") as f:
            f.write(response.content)

        log(f"Photo saved: {local_path}")
        return str(local_path)

    except Exception as e:
        log(f"Error downloading photo: {e}")
        return None


def download_voice(file_id):
    """Download a voice note from Telegram and return the local path."""
    try:
        # Get file info from Telegram
        result = requests.post(f"{API_BASE}/getFile", json={"file_id": file_id}, timeout=30).json()
        if not result.get("ok"):
            log(f"Failed to get voice file info: {result}")
            return None

        file_path = result.get("result", {}).get("file_path")
        if not file_path:
            log("No file_path in voice response")
            return None

        # Download the file
        download_url = f"{FILE_API_BASE}/{file_path}"
        response = requests.get(download_url, timeout=60)

        if response.status_code != 200:
            log(f"Voice download failed with status {response.status_code}")
            return None

        # Save with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        ext = Path(file_path).suffix or ".ogg"
        local_filename = f"voice_{timestamp}{ext}"
        local_path = VOICE_DIR / local_filename

        with open(local_path, "wb") as f:
            f.write(response.content)

        log(f"Voice saved: {local_path}")
        return str(local_path)

    except Exception as e:
        log(f"Error downloading voice: {e}")
        return None


def transcribe_audio(audio_path):
    """Transcribe audio file using Whisper. Returns transcribed text."""
    try:
        model = get_whisper_model()
        log(f"Transcribing: {audio_path}")

        result = model.transcribe(audio_path)
        text = result["text"].strip()

        log(f"Transcription complete: {text[:50]}...")
        return text

    except Exception as e:
        log(f"Transcription error: {e}")
        return None


def poll_telegram(offset):
    """
    Long-poll Telegram for updates.
    Returns list of updates or empty list on error.
    """
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
    params = {
        "timeout": POLL_TIMEOUT,
        "offset": offset
    }

    try:
        response = requests.get(url, params=params, timeout=POLL_TIMEOUT + 5)
        data = response.json()

        if data.get("ok"):
            return data.get("result", [])
        else:
            log(f"API error: {data.get('description', 'Unknown')}")
            return []

    except requests.exceptions.Timeout:
        # Normal for long polling
        return []
    except requests.exceptions.RequestException as e:
        log(f"Network error: {e}")
        return []
    except json.JSONDecodeError:
        log("Invalid JSON response")
        return []

# === MESSAGE HANDLING ===
def write_message(text):
    """Write message to trigger files for AHK."""
    # Write message content
    with open(INCOMING_FILE, "w", encoding="utf-8") as f:
        f.write(text)

    # Create flag file (signals AHK that message is ready)
    with open(FLAG_FILE, "w") as f:
        f.write("1")

    log(f"Message queued: {text[:50]}...")

def process_update(update):
    """Process a single update from Telegram."""
    message = update.get("message", {})
    chat = message.get("chat", {})

    # Only process messages from your chat
    if str(chat.get("id")) != CHAT_ID:
        log(f"Ignoring message from chat {chat.get('id')}")
        return

    caption = message.get("caption", "")
    output_text = None

    # Check for compressed photo
    photo = message.get("photo")
    if photo:
        log("Photo detected, downloading...")
        largest_photo = photo[-1]  # Last one is highest resolution
        file_id = largest_photo.get("file_id")
        local_path = download_photo(file_id)

        if local_path:
            if caption:
                output_text = f"[Photo: {local_path}] {caption}"
            else:
                output_text = f"[Photo: {local_path}]"
        else:
            output_text = "[Photo received but download failed]"

    # Check for document (image sent as file)
    elif message.get("document"):
        doc = message.get("document")
        mime_type = doc.get("mime_type", "")
        file_name = doc.get("file_name", "file")

        if mime_type.startswith("image/"):
            log(f"Image document detected: {file_name}")
            file_id = doc.get("file_id")
            local_path = download_photo(file_id, file_name)

            if local_path:
                if caption:
                    output_text = f"[Image: {local_path}] {caption}"
                else:
                    output_text = f"[Image: {local_path}]"
            else:
                output_text = f"[Image {file_name} received but download failed]"
        else:
            log(f"Non-image document received: {file_name} ({mime_type})")
            output_text = f"[File received: {file_name}]"

    # Check for voice message
    elif message.get("voice"):
        voice = message.get("voice")
        file_id = voice.get("file_id")
        duration = voice.get("duration", 0)
        log(f"Voice message detected, duration: {duration}s")

        # Download the voice note
        voice_path = download_voice(file_id)
        if voice_path:
            # Transcribe using Whisper
            transcription = transcribe_audio(voice_path)
            if transcription:
                output_text = f"[Voice Note] {transcription}"
            else:
                output_text = "[Voice Note - transcription failed]"
        else:
            output_text = "[Voice Note - download failed]"

    # Check for audio message (music/audio files)
    elif message.get("audio"):
        audio = message.get("audio")
        file_name = audio.get("file_name", "audio")
        log(f"Audio file received: {file_name}")
        output_text = f"[Audio File: {file_name}]"

    # Regular text message
    else:
        text = message.get("text", "")
        if text:
            output_text = text

    # If we have something to send, write it
    if not output_text:
        log("Message has no processable content, skipping")
        return

    # Wait if previous message hasn't been processed yet
    wait_count = 0
    while FLAG_FILE.exists() and wait_count < 30:
        log("Waiting for previous message to be processed...")
        time.sleep(1)
        wait_count += 1

    if FLAG_FILE.exists():
        log("WARNING: Previous message not processed, overwriting")

    # Add [Telegram] prefix here (consistent with Discord listener adding [Discord:] prefix)
    if not output_text.startswith("[Discord:"):
        output_text = f"[Telegram] {output_text}"

    write_message(output_text)

# === MAIN LOOP ===
def main():
    # Validate config
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE" or CHAT_ID == "YOUR_CHAT_ID_HERE":
        print("ERROR: Please edit the CONFIG section at the top of this file!")
        print("You need to set your BOT_TOKEN and CHAT_ID.")
        input("Press Enter to exit...")
        sys.exit(1)

    log("=" * 50)
    log("Unified Listener starting...")
    log(f"Watching Telegram chat {CHAT_ID}")
    log(f"Photos will be saved to: {PHOTOS_DIR}")
    log(f"Voice notes will be saved to: {VOICE_DIR}")
    
    # Start Discord listener in a thread
    if DISCORD_AVAILABLE:
        log("Starting Discord listener thread...")
        discord_thread = start_discord_thread()
        log("Discord listener thread launched!")
    else:
        log("WARNING: discord_listener.py not found or discord.py not installed")
        log("Running Telegram-only mode")
    
    log("=" * 50)

    offset = load_state()
    if offset:
        offset += 1  # Start from next message
        log(f"Resuming from offset {offset}")
    else:
        log("Starting fresh (no saved state)")

    while True:
        try:
            # Check for pause file
            if PAUSE_FILE.exists():
                log("PAUSED - delete pause.txt to resume")
                time.sleep(5)
                continue

            updates = poll_telegram(offset)

            for update in updates:
                update_id = update.get("update_id", 0)
                process_update(update)

                # Update offset to acknowledge this message
                if update_id >= offset:
                    offset = update_id + 1
                    save_state(update_id)

        except KeyboardInterrupt:
            log("Shutting down...")
            break
        except Exception as e:
            log(f"Unexpected error: {e}")
            time.sleep(RETRY_DELAY)

if __name__ == "__main__":
    main()
