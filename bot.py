"""
Telegram Group Helper Bot — Channel APK Search with Gemini AI
=============================================================
Monitors a Telegram channel for posts containing #AppName tags.
When a user in a group mentions an app name, the bot uses Gemini AI
to extract the app name from the message, then searches the channel
database and replies with a direct link to the LATEST post.

Gemini AI enables:
- Smart app name extraction from messy sentences
- Spelling mistake tolerance ("reemni" → "Remini")
- Hinglish sentence understanding
- Fuzzy matching when exact match fails
"""

import os
import re
import asyncio
import logging
import sqlite3
import threading
from html import escape
from http.server import BaseHTTPRequestHandler, HTTPServer

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

CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "")
CHANNEL_ID = os.getenv("CHANNEL_ID", "")
DB_PATH = os.getenv("DB_PATH", "bot_data.db")
PORT = int(os.getenv("PORT", "10000"))

API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
SESSION_STRING = os.getenv("SESSION_STRING", "").strip()

# Gemini AI
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

logging.basicConfig(
    format="%(asctime)s — %(name)s — %(levelname)s — %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Keep-alive web server (for Render)
# ---------------------------------------------------------------------------
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Bot is running!")

    def log_message(self, format, *args):
        pass


def start_keep_alive(port: int) -> None:
    try:
        server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
        logger.info("Keep-alive server listening on port %d", port)
        server.serve_forever()
    except OSError as e:
        logger.warning("Could not start keep-alive server: %s", e)


# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------
HASHTAG_PATTERN = re.compile(r"#([a-zA-Z0-9][a-zA-Z0-9 _]{1,40})", re.IGNORECASE)

NOISE_WORDS = frozenset({
    "bhai", "bro", "dude", "mate", "yo", "pls", "please", "kya", "hai",
    "hain", "nahi", "haan", "ka", "ki", "ke", "ko", "me", "mein", "se",
    "par", "aur", "ya", "to", "bhi", "hi", "tha", "thi", "the", "ho",
    "de", "do", "dila", "dilado", "chahiye", "chahiya",
    "mujhe", "muje", "mujhko", "hamko", "humko", "merako",
    "apk", "app", "mod", "update", "krdo", "kar", "karo", "dena", "de do",
    "bhejo", "send", "link", "download", "latest", "new", "old", "version",
    "the", "a", "an", "is", "am", "are", "was", "were", "be", "been",
    "and", "or", "but", "if", "so", "for", "of", "to", "in", "on", "at",
    "by", "with", "from", "this", "that", "it", "as",
    "hi", "hello", "hey", "hlo", "hii", "helo", "namaste", "namaskar",
    "ok", "okay", "thanks", "thank", "thx", "sorry", "bye",
    "bot", "admin", "group", "channel", "k", "kk", "hmm", "hmmm",
    "wow", "nice", "cool", "good", "bad", "fine", "great",
    "sir", "madam", "master", "boss",
})


# ---------------------------------------------------------------------------
# Gemini AI — Smart app name extraction
# ---------------------------------------------------------------------------
_gemini_model = None


def init_gemini():
    """Initialize Gemini AI model. Call once at startup."""
    global _gemini_model
    if not GEMINI_API_KEY:
        logger.info("GEMINI_API_KEY not set — AI features disabled, using fallback.")
        return False
    try:
        import google.generativeai as genai
        genai.configure(api_key=GEMINI_API_KEY)
        _gemini_model = genai.GenerativeModel(
            "gemini-1.5-flash",
            system_instruction=(
                "You are an app name extractor bot. "
                "Given a message from a Telegram group user, extract the app name "
                "they are looking for. "
                "Respond with ONLY the app name, nothing else. "
                "If the message is not about an app, respond with 'NONE'. "
                "Handle spelling mistakes, Hinglish, and messy sentences. "
                "Examples:\n"
                "Input: 'bhai remini ka apk update krdo pls' → Output: Remini\n"
                "Input: 'I stream flare apk chahiye' → Output: I Stream Flare\n"
                "Input: 'capcut mod dedo bhai' → Output: CapCut\n"
                "Input: 'hello kaise ho' → Output: NONE\n"
                "Input: 'reemni' → Output: Remini\n"
                "Input: '#QuickTv' → Output: QuickTv\n"
            ),
        )
        logger.info("✅ Gemini AI initialized successfully.")
        return True
    except Exception as e:
        logger.error("Failed to initialize Gemini AI: %s", e)
        return False


async def gemini_extract_app_name(message_text: str) -> str:
    """
    Use Gemini AI to extract the app name from a user message.
    Returns the app name, or empty string if not an app request.
    Falls back to heuristic method if Gemini fails.
    """
    if not _gemini_model:
        return extract_app_name_from_sentence(message_text)

    try:
        # Run Gemini in a thread to avoid blocking the event loop
        def call_gemini():
            response = _gemini_model.generate_content(
                f"Extract the app name from this message:\n{message_text}"
            )
            return response.text.strip()

        result = await asyncio.to_thread(call_gemini)

        # Clean up the response
        result = result.strip().strip('"').strip("'").strip()

        if result.upper() == "NONE" or not result or len(result) < 2:
            return ""

        logger.info("Gemini extracted app name: '%s' from '%s'", result, message_text)
        return result
    except Exception as e:
        logger.warning("Gemini AI failed (%s), falling back to heuristic.", e)
        return extract_app_name_from_sentence(message_text)


async def gemini_fuzzy_search(app_name: str, db_results: list) -> list:
    """
    Use Gemini AI to pick the best match from database results
    when exact match is not found.
    """
    if not _gemini_model or not db_results:
        return db_results

    try:
        app_names_in_db = [r["app_name"] for r in db_results if r["app_name"]]
        if not app_names_in_db:
            return db_results

        def call_gemini():
            prompt = (
                f"The user searched for: '{app_name}'\n"
                f"Available apps in database:\n"
            )
            for i, name in enumerate(app_names_in_db, 1):
                prompt += f"{i}. {name}\n"
            prompt += (
                f"\nWhich of these apps is the user most likely looking for? "
                f"Respond with ONLY the app name, or 'NONE' if no good match."
            )
            response = _gemini_model.generate_content(prompt)
            return response.text.strip()

        result = await asyncio.to_thread(call_gemini)
        result = result.strip().strip('"').strip("'").strip()

        if result.upper() == "NONE":
            return []

        # Find matching result
        for post in db_results:
            if post["app_name"] and post["app_name"].lower() == result.lower():
                logger.info("Gemini fuzzy match: '%s' → '%s'", app_name, result)
                return [post]

        return db_results
    except Exception as e:
        logger.warning("Gemini fuzzy search failed (%s), returning raw results.", e)
        return db_results


# ---------------------------------------------------------------------------
# Database
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


def store_post(message_id, chat_id, app_name, full_text, link, created_at=None):
    conn = sqlite3.connect(DB_PATH)
    if created_at:
        conn.execute(
            "INSERT OR REPLACE INTO channel_posts "
            "(message_id, chat_id, app_name, full_text, link, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (message_id, chat_id, app_name, full_text, link, created_at),
        )
    else:
        conn.execute(
            "INSERT OR REPLACE INTO channel_posts "
            "(message_id, chat_id, app_name, full_text, link) "
            "VALUES (?, ?, ?, ?, ?)",
            (message_id, chat_id, app_name, full_text, link),
        )
    conn.commit()
    conn.close()


def search_by_app_name(query: str, limit: int = 5) -> list:
    conn = sqlite3.connect(DB_PATH)
    query_clean = query.strip().lower().replace(" ", "")

    # 1) Exact match (newest first)
    cursor = conn.execute(
        "SELECT app_name, full_text, link, message_id FROM channel_posts "
        "WHERE LOWER(REPLACE(app_name, ' ', '')) = ? "
        "ORDER BY created_at DESC",
        (query_clean,),
    )
    results = [
        {"app_name": r[0], "text": r[1], "link": r[2], "message_id": r[3]}
        for r in cursor.fetchall()
    ]

    # 2) Partial / LIKE match (newest first)
    if not results:
        like_query = f"%{query.strip().lower()}%"
        cursor = conn.execute(
            "SELECT app_name, full_text, link, message_id FROM channel_posts "
            "WHERE LOWER(app_name) LIKE ? OR LOWER(full_text) LIKE ? "
            "ORDER BY created_at DESC",
            (like_query, like_query),
        )
        results = [
            {"app_name": r[0], "text": r[1], "link": r[2], "message_id": r[3]}
            for r in cursor.fetchall()
        ]

    conn.close()

    # 3) Deduplicate: keep only LATEST post per app_name
    seen_apps = set()
    deduped = []
    for post in results:
        app_key = (post["app_name"] or "").strip().lower().replace(" ", "")
        if app_key not in seen_apps:
            seen_apps.add(app_key)
            deduped.append(post)
        if len(deduped) >= limit:
            break

    return deduped


def get_all_app_names() -> list:
    """Get all unique app names from the database (for fuzzy matching)."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.execute(
        "SELECT DISTINCT app_name FROM channel_posts "
        "WHERE app_name IS NOT NULL ORDER BY app_name"
    )
    names = [r[0] for r in cursor.fetchall()]
    conn.close()
    return names


def get_post_count() -> int:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.execute("SELECT COUNT(*) FROM channel_posts")
    count = cursor.fetchone()[0]
    conn.close()
    return count


def build_message_link(chat_id: int, message_id: int) -> str:
    if CHANNEL_USERNAME:
        return f"https://t.me/{CHANNEL_USERNAME}/{message_id}"
    if chat_id < 0:
        positive_id = str(chat_id).replace("-100", "", 1)
        return f"https://t.me/c/{positive_id}/{message_id}"
    return f"https://t.me/c/{chat_id}/{message_id}"


# ---------------------------------------------------------------------------
# Text extraction (fallback for when Gemini is not available)
# ---------------------------------------------------------------------------
def extract_hashtags(text: str) -> list:
    matches = HASHTAG_PATTERN.findall(text)
    cleaned = []
    for m in matches:
        name = m.strip()
        if name and len(name) >= 2:
            cleaned.append(name)
    return cleaned


def extract_text_from_message(message) -> str:
    if message.text:
        return message.text
    if message.caption:
        return message.caption
    return ""


def extract_app_name_from_sentence(text: str) -> str:
    """Fallback: extract app name using heuristics (when Gemini is not available)."""
    text = text.strip()
    hashtags = extract_hashtags(text)
    if hashtags:
        return hashtags[0]
    cleaned = re.sub(r"[^\w\s]", " ", text)
    words = cleaned.split()
    app_words = [w for w in words if w.lower() not in NOISE_WORDS and len(w) >= 2]
    if not app_words:
        return ""
    return " ".join(app_words)


def is_search_request(text: str) -> bool:
    text = text.strip()
    if not text or len(text) < 2:
        return False
    if HASHTAG_PATTERN.search(text):
        return True
    text_lower = text.lower()
    app_keywords = {"apk", "app", "mod", "update", "link", "download",
                    "latest", "version", "chahiye", "chahiya", "dila",
                    "dilado", "bhejo", "dena", "dedo", "krdo", "karo"}
    words = set(re.sub(r"[^\w\s]", " ", text_lower).split())
    if app_keywords & words:
        return True
    word_count = len(text.split())
    if word_count <= 4:
        non_noise = [
            w for w in text.split()
            if w.lower().strip(".,!?;:'\"") not in NOISE_WORDS
            and len(w.strip(".,!?;:'\"")) >= 2
        ]
        if non_noise:
            return True
    return False


# ---------------------------------------------------------------------------
# Auto-import channel history (Telethon)
# ---------------------------------------------------------------------------
def get_channel_target():
    if CHANNEL_USERNAME:
        return CHANNEL_USERNAME
    if CHANNEL_ID:
        return int(CHANNEL_ID)
    return None


async def auto_import_history_async():
    if not SESSION_STRING:
        logger.warning(
            "SESSION_STRING not set — skipping auto-import. "
            "Run generate_session.py locally to get a session string."
        )
        return 0

    if not API_ID or not API_HASH:
        logger.warning("API_ID/API_HASH not set — skipping auto-import.")
        return 0

    channel_target = get_channel_target()
    if not channel_target:
        logger.warning("CHANNEL_USERNAME or CHANNEL_ID not set — skipping.")
        return 0

    try:
        from telethon import TelegramClient
        from telethon.sessions import StringSession
    except ImportError:
        logger.error("Telethon not installed! Run: pip install telethon")
        return 0

    logger.info("Starting auto-import using Telethon user session...")
    imported = 0
    skipped = 0

    client = None
    try:
        client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
        await client.start()
        logger.info("Telethon user session started, reading channel history...")

        entity = await client.get_entity(channel_target)
        logger.info("Resolved channel entity: %s", getattr(entity, 'title', str(channel_target)))

        async for message in client.iter_messages(entity):
            text = message.text or message.message or ""
            if not text:
                skipped += 1
                continue

            chat_id = message.chat_id or message.peer_id.channel_id
            if hasattr(message.peer_id, 'channel_id'):
                chat_id = -1000000000000 - message.peer_id.channel_id
            message_id = message.id
            link = build_message_link(chat_id, message_id)

            hashtags = extract_hashtags(text)
            if hashtags:
                app_name = hashtags[0]
            else:
                skipped += 1
                continue

            created_at = message.date.isoformat() if message.date else None
            store_post(message_id, chat_id, app_name, text, link, created_at)
            imported += 1

            if imported % 100 == 0:
                logger.info("Auto-import: %d posts imported so far...", imported)

        logger.info(
            "✅ Auto-import complete! Imported: %d posts, Skipped: %d",
            imported, skipped,
        )
    except Exception as e:
        logger.error("Auto-import failed: %s", e)
    finally:
        if client:
            try:
                await client.disconnect()
            except Exception:
                pass

    return imported


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    count = get_post_count()
    ai_status = "✅ Enabled" if _gemini_model else "❌ Disabled"
    text = (
        "👋 *Hello!*\n\n"
        "I'm a *Channel APK Search Bot* with AI.\n\n"
        "📋 *How to use:*\n"
        "• Type an app name and I'll find it in the channel\n"
        "• You can use `#AppName` or just type the name\n"
        "• Type a full sentence: `bhai remini ka apk update krdo pls`\n"
        "• Spelling mistakes are OK — AI will understand!\n\n"
        "✨ *Examples:*\n"
        "• `#QuickTv`\n"
        "• `remini`\n"
        "• `bhai capcut ka mod dila do`\n"
        "• `reemni` (spelling mistake — AI will fix!)\n\n"
        "📌 I always give the *latest* link for each app.\n"
        f"🤖 AI: {ai_status}\n\n"
        f"📚 Currently tracking *{count}* channel posts."
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    count = get_post_count()
    ai_status = "✅ Enabled" if _gemini_model else "❌ Disabled"
    await update.message.reply_text(
        f"📊 *Bot Statistics*\n\n"
        f"📚 Total channel posts: *{count}*\n"
        f"🤖 AI: {ai_status}",
        parse_mode="Markdown",
    )


async def import_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not SESSION_STRING:
        await update.message.reply_text(
            "❌ Import not available.\n"
            "Session string not configured. "
            "Run generate_session.py locally first."
        )
        return

    await update.message.reply_text(
        "⏳ Importing channel history... This may take a few minutes."
    )

    def run_import():
        asyncio.run(auto_import_history_async())

    thread = threading.Thread(target=run_import, daemon=True)
    thread.start()

    count = get_post_count()
    await update.message.reply_text(
        f"✅ Import started! Current database has *{count}* posts.\n"
        f"Run /stats after a minute to check updated count.",
        parse_mode="Markdown",
    )


async def channel_post_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if not update.channel_post:
        return
    post = update.channel_post
    text = extract_text_from_message(post)
    if not text:
        return
    chat_id = post.chat.id
    message_id = post.message_id
    link = build_message_link(chat_id, message_id)
    hashtags = extract_hashtags(text)
    if hashtags:
        app_name = hashtags[0]
    else:
        app_name = text[:50]
    store_post(message_id, chat_id, app_name, text, link)
    logger.info(
        "Stored channel post %s — app: %s (text: %.50s...)",
        message_id, app_name, text,
    )


async def find_app(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return

    message_text = update.message.text

    if not is_search_request(message_text):
        return

    # Use Gemini AI to extract app name (falls back to heuristic if no AI)
    app_query = await gemini_extract_app_name(message_text)

    if not app_query or len(app_query) < 2:
        return

    logger.info(
        "Searching for: '%s' (extracted from: '%s') — user: %s, chat: %s",
        app_query, message_text,
        update.effective_user.username or update.effective_user.id,
        update.effective_chat.id,
    )

    results = search_by_app_name(app_query, limit=5)

    # If no exact match, use Gemini for fuzzy matching
    if not results and _gemini_model:
        logger.info("No exact match — using Gemini fuzzy search...")
        all_names = get_all_app_names()
        if all_names:
            # Get some candidate results using broad LIKE search
            broad_results = []
            for name in all_names[:50]:  # Limit to prevent too many queries
                if app_query.lower().split()[0] in name.lower():
                    conn = sqlite3.connect(DB_PATH)
                    cursor = conn.execute(
                        "SELECT app_name, full_text, link, message_id "
                        "FROM channel_posts WHERE LOWER(app_name) = ? "
                        "ORDER BY created_at DESC LIMIT 1",
                        (name.lower(),),
                    )
                    for r in cursor.fetchall():
                        broad_results.append(
                            {"app_name": r[0], "text": r[1], "link": r[2], "message_id": r[3]}
                        )
                    conn.close()

            if broad_results:
                results = await gemini_fuzzy_search(app_query, broad_results)

    if not results:
        if HASHTAG_PATTERN.search(message_text):
            await update.message.reply_text(
                f"❌ No match found for *{escape(app_query)}*.\n"
                f"This app might not be in the channel yet.",
                parse_mode="Markdown",
            )
        return

    if len(results) == 1:
        post = results[0]
        preview = (post["text"] or "")[:120]
        if len(post["text"] or "") > 120:
            preview += "..."
        reply = (
            f"📱 *{escape(post['app_name'] or app_query)}*\n\n"
            f"📝 {escape(preview)}\n\n"
            f"🔗 [Open Post]({post['link']})"
        )
        await update.message.reply_text(
            reply, parse_mode="Markdown", disable_web_page_preview=False
        )
    else:
        lines = [f"📱 *Found {len(results)} matches for* `{escape(app_query)}`:\n"]
        for i, post in enumerate(results, 1):
            preview = (post["text"] or "")[:60]
            if len(post["text"] or "") > 60:
                preview += "..."
            lines.append(
                f"{i}. *{escape(post['app_name'] or 'Unknown')}*\n"
                f"   {escape(preview)}\n"
                f"   🔗 [Open]({post['link']})"
            )
        await update.message.reply_text(
            "\n".join(lines), parse_mode="Markdown",
            disable_web_page_preview=True
        )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Exception: %s", context.error)


async def post_init(application: Application) -> None:
    """Run after bot init — initialize AI and auto-import if needed."""
    # Initialize Gemini AI
    init_gemini()

    count = get_post_count()
    if count == 0:
        logger.info("Database is empty — running auto-import...")
        await auto_import_history_async()
    else:
        logger.info("Database has %d posts — skipping auto-import.", count)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    init_db()

    keep_alive_thread = threading.Thread(
        target=start_keep_alive, args=(PORT,), daemon=True
    )
    keep_alive_thread.start()

    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", start_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("import", import_command))

    app.add_handler(
        MessageHandler(filters.UpdateType.CHANNEL_POSTS, channel_post_handler)
    )
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND & filters.ChatType.GROUPS,
            find_app,
        )
    )

    app.add_error_handler(error_handler)

    logger.info("Bot is starting... Press Ctrl+C to stop.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
