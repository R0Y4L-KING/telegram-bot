"""
Telegram Group Helper Bot
Monitors a Telegram channel for posts and stores them in a database.
When a user in a group types an app name, the bot searches the channel
posts and replies with a direct link to the matching post.
"""

import os
import re
import logging
import sqlite3
from html import escape

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN not found! Set it in your .env file or environment variable.\n"
        "Get a token from @BotFather on Telegram."
    )

# Channel username (without @) — for building public message links.
# Leave empty if the channel is private; the bot will use the private link format.
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "")
CHANNEL_ID = os.getenv("CHANNEL_ID", "")  # e.g. -1001234567890

DB_PATH = os.getenv("DB_PATH", "bot_data.db")

# Logging
logging.basicConfig(
    format="%(asctime)s — %(name)s — %(levelname)s — %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Common words to ignore — these should NOT trigger a search.
IGNORE_WORDS = frozenset({
    "hi", "hello", "hey", "ok", "okay", "yes", "no", "lol", "haha",
    "thanks", "thank", "thx", "pls", "please", "sorry", "bye", "gn",
    "gm", "good", "morning", "night", "what", "why", "how", "who",
    "where", "when", "kya", "hai", "hain", "nahi", "haan", "bhai",
    "bro", "dude", "mate", "yo", "sup", "wow", "nice", "cool", "great",
    "the", "and", "for", "are", "you", "all", "can", "get", "got",
    "this", "that", "was", "has", "had", "but", "not", "will", "just",
    "dont", "cant", "wont", "ill", "youre", "they", "them", "here",
    "there", "now", "then", "one", "two", "also", "very", "much",
    "any", "some", "more", "out", "about", "into", "from", "with",
    "have", "your", "been", "were", "said", "each", "which", "their",
    "would", "could", "should", "stop", "wait", "let", "me", "my",
    "we", "us", "our", "he", "she", "it", "is", "am", "do", "so",
    "if", "or", "as", "at", "by", "in", "on", "to", "up", "of",
    "a", "an", "go", "no", "bot", "admin", "mod", "owner", "group",
    "channel", "link", "send", "give", "take", "make", "find",
    "search", "help", "start", "begin", "end", "pause", "play",
    "next", "prev", "back", "forward", "left", "right", "down",
    "top", "bottom", "chat", "msg", "text", "call", "video",
    "audio", "photo", "pic", "image", "file", "doc", "pdf", "zip",
    "apk", "app", "download", "upload", "share", "copy", "paste",
    "delete", "remove", "add", "new", "old", "best", "worst",
    "free", "paid", "pro", "lite", "beta", "alpha", "test", "demo",
    "trial", "full", "final", "version", "update", "install",
    "uninstall", "setup", "run", "code", "script", "tool", "site",
    "website", "blog", "page", "post", "reply", "comment", "like",
    "love", "hate", "want", "need", "wish", "hope", "try", "use",
    "using", "used", "getting", "going", "coming", "looking",
    "finding", "trying", "making", "doing", "saying", "talking",
    "asking", "telling", "knowing", "thinking", "feeling", "seeing",
    "hearing", "reading", "writing", "typing", "k", "kk", "okayy",
    "hlo", "hii", "helo", "helloo", "namaste", "namaskar", "salaam",
    "salam", "adaab", "hmm", "hmmm", "oh", "ah", "uff", "wow",
    "nice", "good", "bad", "fine", "ok", "okay", "alright",
})


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
def init_db() -> None:
    """Create the database table if it does not exist."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS channel_posts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id  INTEGER NOT NULL,
            chat_id     INTEGER NOT NULL,
            text        TEXT,
            link        TEXT,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_text ON channel_posts(text)"
    )
    conn.commit()
    conn.close()


def store_post(message_id: int, chat_id: int, text: str, link: str) -> None:
    """Store a channel post in the database."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT OR REPLACE INTO channel_posts (message_id, chat_id, text, link) "
        "VALUES (?, ?, ?, ?)",
        (message_id, chat_id, text, link),
    )
    conn.commit()
    conn.close()


def search_posts(query: str, limit: int = 5) -> list:
    """
    Search channel posts by text.
    Returns a list of dicts with keys: text, link, message_id.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.execute(
        "SELECT text, link, message_id FROM channel_posts "
        "WHERE text LIKE ? COLLATE NOCASE "
        "ORDER BY created_at DESC LIMIT ?",
        (f"%{query}%", limit),
    )
    results = [
        {"text": row[0], "link": row[1], "message_id": row[2]}
        for row in cursor.fetchall()
    ]
    conn.close()
    return results


def get_post_count() -> int:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.execute("SELECT COUNT(*) FROM channel_posts")
    count = cursor.fetchone()[0]
    conn.close()
    return count


def build_message_link(chat_id: int, message_id: int) -> str:
    """
    Build a Telegram link to a channel post.
    - Public channel with username: https://t.me/{username}/{message_id}
    - Private channel: https://t.me/c/{chat_id_without_prefix}/{message_id}
    """
    if CHANNEL_USERNAME:
        return f"https://t.me/{CHANNEL_USERNAME}/{message_id}"

    # For private channels, chat_id is like -1001234567890
    # The link format uses the positive part without the -100 prefix
    if chat_id < 0:
        # Remove the -100 prefix for private supergroups/channels
        positive_id = str(chat_id).replace("-100", "", 1)
        return f"https://t.me/c/{positive_id}/{message_id}"

    return f"https://t.me/c/{chat_id}/{message_id}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def is_likely_app_name(text: str) -> bool:
    """
    Heuristic: decide if a message looks like an app-name search.
    - Must be a single word (no spaces).
    - At least 3 characters.
    - Mostly alphabetic.
    - Not a common word.
    """
    text = text.strip()

    if not text or " " in text or len(text) < 3:
        return False

    alpha_count = sum(1 for c in text if c.isalpha())
    if alpha_count < len(text) * 0.5:
        return False

    # Strip common trailing punctuation
    cleaned = text.rstrip(".,!?;:'\"")
    if cleaned.lower() in IGNORE_WORDS:
        return False

    return True


def extract_text_from_message(message) -> str:
    """Extract text content from a Telegram message (caption, text, or forwarded)."""
    if message.text:
        return message.text
    if message.caption:
        return message.caption
    if message.forward_origin:
        # Try to get text from forwarded message
        if hasattr(message, "text") and message.text:
            return message.text
        if hasattr(message, "caption") and message.caption:
            return message.caption
    return ""


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start and /help commands."""
    count = get_post_count()
    text = (
        "👋 *Hello!*\n\n"
        "I'm a *Channel Search Bot*.\n\n"
        "📋 *How to use:*\n"
        "Just type an app name in the group and I'll search for it "
        "in the linked channel and give you the direct post link.\n\n"
        "✨ *Examples:*\n"
        "• `remini` — Find Remini post\n"
        "• `capcut` — Find CapCut post\n"
        "• `truecaller` — Find Truecaller post\n\n"
        f"📚 Currently tracking *{count}* channel posts.\n\n"
        "⚠️ I only respond to single-word searches, not full sentences."
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /stats command — show database stats."""
    count = get_post_count()
    await update.message.reply_text(
        f"📊 *Bot Statistics*\n\n"
        f"📚 Total channel posts indexed: *{count}*",
        parse_mode="Markdown",
    )


async def channel_post_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Handle new channel posts — store them in the database.
    This runs automatically when the bot is an admin in the channel.
    """
    if not update.channel_post:
        return

    post = update.channel_post
    text = extract_text_from_message(post)

    if not text:
        return

    chat_id = post.chat.id
    message_id = post.message_id
    link = build_message_link(chat_id, message_id)

    store_post(message_id, chat_id, text, link)
    logger.info(
        "Stored channel post %s from chat %s (text: %.50s...)",
        message_id,
        chat_id,
        text,
    )


async def find_app(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    When a user types a single word in the group, search the channel
    post database and reply with matching post links.
    """
    message_text = update.message.text or ""

    # Clean trailing punctuation
    cleaned = message_text.strip().rstrip(".,!?;:'\"")

    if not is_likely_app_name(cleaned):
        return

    app_query = cleaned
    logger.info(
        "Searching for: %s (user: %s, chat: %s)",
        app_query,
        update.effective_user.username or update.effective_user.id,
        update.effective_chat.id,
    )

    results = search_posts(app_query, limit=5)

    if not results:
        # Don't spam — silently ignore if no match
        return

    if len(results) == 1:
        post = results[0]
        preview = post["text"][:100] + ("..." if len(post["text"]) > 100 else "")
        reply = (
            f"📱 *Found a match for* `{escape(app_query)}`:\n\n"
            f"📝 {escape(preview)}\n\n"
            f"🔗 [Open Post]({post['link']})"
        )
        await update.message.reply_text(
            reply, parse_mode="Markdown", disable_web_page_preview=False
        )
    else:
        lines = [f"📱 *Found {len(results)} matches for* `{escape(app_query)}`:\n"]
        for i, post in enumerate(results, 1):
            preview = post["text"][:60] + ("..." if len(post["text"]) > 60 else "")
            lines.append(f"{i}. {escape(preview)}\n   🔗 [Open]({post['link']})")
        await update.message.reply_text(
            "\n".join(lines), parse_mode="Markdown", disable_web_page_preview=True
        )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log errors."""
    logger.error("Exception: %s", context.error)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    """Start the bot."""
    init_db()

    app = Application.builder().token(BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", start_command))
    app.add_handler(CommandHandler("stats", stats_command))

    # Channel post handler — stores new posts from the channel
    app.add_handler(
        MessageHandler(filters.UpdateType.CHANNEL_POSTS, channel_post_handler)
    )

    # Group message handler — search when user types a single word
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND & filters.ChatType.GROUPS,
            find_app,
        )
    )

    # Error handler
    app.add_error_handler(error_handler)

    logger.info("Bot is starting... Press Ctrl+C to stop.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
