"""
Channel History Import Script
=============================
Run this script ONCE to import all existing channel posts into the bot's database.
The Telegram Bot API cannot read channel history, so we use Pyrogram (MTProto API)
which allows bots that are channel admins to read past messages.

Usage:
    python import_history.py

Requirements:
    - Bot must be added as admin to the channel
    - Set BOT_TOKEN and CHANNEL_USERNAME (or CHANNEL_ID) in .env file
"""

import os
import re
import sqlite3
import logging
from dotenv import load_dotenv
from pyrogram import Client

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "")  # without @
CHANNEL_ID = os.getenv("CHANNEL_ID", "")  # e.g. -1001234567890
DB_PATH = os.getenv("DB_PATH", "bot_data.db")

API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN not set in .env file!")
if not API_ID or not API_HASH:
    raise RuntimeError(
        "API_ID and API_HASH not set in .env file!\n"
        "Get them from https://my.telegram.org → API Development Tools"
    )

logging.basicConfig(
    format="%(asctime)s — %(levelname)s — %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Same hashtag pattern as bot.py
HASHTAG_PATTERN = re.compile(r"#([a-zA-Z0-9][a-zA-Z0-9 _]{1,40})", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Database (same schema as bot.py)
# ---------------------------------------------------------------------------
def init_db() -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS channel_posts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id  INTEGER NOT NULL,
            chat_id     INTEGER NOT NULL,
            app_name    TEXT,
            full_text   TEXT,
            link        TEXT,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_app_name ON channel_posts(app_name)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_full_text ON channel_posts(full_text)")
    conn.commit()
    conn.close()


def store_post(message_id, chat_id, app_name, full_text, link):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT OR REPLACE INTO channel_posts "
        "(message_id, chat_id, app_name, full_text, link) "
        "VALUES (?, ?, ?, ?, ?)",
        (message_id, chat_id, app_name, full_text, link),
    )
    conn.commit()
    conn.close()


def get_post_count():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.execute("SELECT COUNT(*) FROM channel_posts")
    count = cursor.fetchone()[0]
    conn.close()
    return count


def extract_hashtags(text):
    matches = HASHTAG_PATTERN.findall(text)
    cleaned = []
    for m in matches:
        name = m.strip()
        if name and len(name) >= 2:
            cleaned.append(name)
    return cleaned


def build_message_link(chat_id, message_id):
    if CHANNEL_USERNAME:
        return f"https://t.me/{CHANNEL_USERNAME}/{message_id}"
    if chat_id < 0:
        positive_id = str(chat_id).replace("-100", "", 1)
        return f"https://t.me/c/{positive_id}/{message_id}"
    return f"https://t.me/c/{chat_id}/{message_id}"


# ---------------------------------------------------------------------------
# Main import logic
# ---------------------------------------------------------------------------
def main():
    init_db()

    # Determine channel target
    if CHANNEL_USERNAME:
        channel_target = CHANNEL_USERNAME
    elif CHANNEL_ID:
        channel_target = int(CHANNEL_ID)
    else:
        raise RuntimeError(
            "Either CHANNEL_USERNAME or CHANNEL_ID must be set in .env file!"
        )

    # Initialize Pyrogram client with bot token
    app = Client(
        "bot_import",
        api_id=API_ID,
        api_hash=API_HASH,
        bot_token=BOT_TOKEN,
        in_memory=True,
    )

    logger.info("Starting channel history import...")
    logger.info("Channel: %s", channel_target)

    imported = 0
    skipped = 0

    with app:
        # Iterate through all channel posts (newest to oldest)
        for message in app.get_chat_history(channel_target):
            # Skip messages without text
            text = message.text or message.caption or ""
            if not text:
                skipped += 1
                continue

            chat_id = message.chat.id
            message_id = message.id
            link = build_message_link(chat_id, message_id)

            # Extract app name from hashtags
            hashtags = extract_hashtags(text)
            if hashtags:
                app_name = hashtags[0]
            else:
                # Skip posts without hashtags — they're probably not app posts
                skipped += 1
                continue

            store_post(message_id, chat_id, app_name, text, link)
            imported += 1

            # Use message date for accurate created_at
            if message.date:
                conn = sqlite3.connect(DB_PATH)
                conn.execute(
                    "UPDATE channel_posts SET created_at = ? WHERE message_id = ? AND chat_id = ?",
                    (message.date.isoformat(), message_id, chat_id),
                )
                conn.commit()
                conn.close()

            if imported % 100 == 0:
                logger.info("Imported %d posts so far...", imported)

    total = get_post_count()
    logger.info("=" * 50)
    logger.info("✅ Import complete!")
    logger.info("   Imported: %d posts", imported)
    logger.info("   Skipped: %d posts (no text or no hashtag)", skipped)
    logger.info("   Total in database: %d posts", total)
    logger.info("=" * 50)


if __name__ == "__main__":
    main()
