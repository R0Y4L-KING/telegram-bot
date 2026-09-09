"""
MODAPPSKING Search Bot with AI
==============================
A Telegram bot that monitors multiple channels for posts containing
#AppName tags. When a user in a group mentions an app name, the bot
uses Gemini AI to extract the app name, searches all configured channels,
and replies with a direct link to the LATEST post.
"""

import os
import re
import time
import asyncio
import logging
import sqlite3
import threading
import urllib.request
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
    raise RuntimeError("BOT_TOKEN not found! Set it in your environment variable.")

CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "")
CHANNEL_ID_ENV = os.getenv("CHANNEL_ID", "")
DB_PATH = os.getenv("DB_PATH", "bot_data.db")
PORT = int(os.getenv("PORT", "10000"))

API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
SESSION_STRING = os.getenv("SESSION_STRING", "").strip()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL", "")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))

logging.basicConfig(
    format="%(asctime)s — %(name)s — %(levelname)s — %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Keep-alive
# ---------------------------------------------------------------------------
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"MODAPPSKING Search Bot is running!")

    def log_message(self, format, *args):
        pass


def start_keep_alive(port: int) -> None:
    try:
        server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
        logger.info("Keep-alive server listening on port %d", port)
        server.serve_forever()
    except OSError as e:
        logger.warning("Could not start keep-alive server: %s", e)


def self_ping():
    if not RENDER_EXTERNAL_URL:
        logger.info("RENDER_EXTERNAL_URL not set — self-ping disabled.")
        return
    ping_url = RENDER_EXTERNAL_URL.rstrip("/") + "/"
    logger.info("Self-ping enabled: will ping %s every 5 minutes", ping_url)
    import time as _time
    while True:
        try:
            urllib.request.urlopen(ping_url, timeout=10)
        except Exception as e:
            logger.warning("Self-ping failed: %s", e)
        _time.sleep(300)


# ---------------------------------------------------------------------------
# Patterns & noise words
# ---------------------------------------------------------------------------
HASHTAG_PATTERN = re.compile(r"#([a-zA-Z0-9][a-zA-Z0-9 _]{1,40})", re.IGNORECASE)

QUICK_SKIP = frozenset({
    "k", "kk", "ok", "okay", "okk", "hmm", "hmmm", "oh", "ah", "uff",
    "lol", "haha", "hehe", "nice", "cool", "good", "bad", "wow",
    "yes", "no", "yo", "sup", "bye", "gn", "gm", "thx", "thanks",
    "thank", "sorry", "pls", "please", "bhai", "bro", "dude", "mate",
    "sir", "madam", "boss", "master", "hi", "hello", "hey", "hlo",
    "hii", "helo", "namaste", "namaskar", "salaam", "adaab",
    "fine", "great", "bot", "admin",
    "haan", "nahi", "nhi", "theek", "thik", "accha", "acha",
    "kya", "kab", "kahan", "kyun", "kyu",
    "already", "uploaded", "done", "ho", "gaya", "gya", "hua", "huaa",
    "done", "finished", "complete", "completed",
    "me", "mein", "main", "hum", "ham", "tu", "tum", "aap",
    "hu", "huu", "hoon", "ho", "hai", "hain",
})

# Phrases that are definitely NOT app searches
NON_SEARCH_PHRASES = frozenset({
    "already uploaded", "already done", "me hi hu", "me hu", "main hu",
    "ab nhi ho payega", "nhi ho payega", "nhi ho payga", "ho gaya",
    "ho gya", "done bhai", "already done", "ok done", "done bro",
    "uploaded already", "kar diya", "kar diya", "kr diya", "krdya",
    "de diya", "de diya", "dedo", "send kar diya",
    "not available", "not found", "nhi hai", "nahi hai",
    "kaise ho", "kaise ho bhai", "kya hal",
})

NOISE_WORDS = frozenset({
    "bhai", "bro", "dude", "mate", "yo", "pls", "please", "kya", "hai",
    "hain", "nahi", "nhi", "haan", "ka", "ki", "ke", "ko", "me", "mein", "se",
    "par", "aur", "ya", "to", "bhi", "hi", "tha", "thi", "the", "ho", "hu",
    "de", "do", "dila", "dilado", "chahiye", "chahiya", "ab", "phle", "pahle",
    "dia", "diya", "payega", "paygi", "hogya", "hogi", "hoga", "gaya",
    "mujhe", "muje", "mujhko", "hamko", "humko", "merako", "mera", "meri",
    "kar", "karo", "krdo", "krdi", "kiya", "karna", "rah", "raha",
    "rahi", "rhe", "reh", "liya", "lena", "lenge", "dene", "denge",
    "wala", "wali", "wale", "kaun", "konsa", "konsi", "kahan", "kab", "kyun",
    "kyu", "aise", "aisa", "aisi", "waise", "waisa", "waisi", "itna", "utna",
    "kitna", "bahut", "phle", "thoda", "zyada", "kam", "jada", "sab", "kuch",
    "jo", "wo", "ye", "vo", "uska", "uski", "unka", "unki",
    "eska", "eski", "pehla", "akhiri", "last", "first",
    "apk", "app", "mod", "update", "krdo", "karo", "dena", "de",
    "bhejo", "send", "link", "download", "latest", "new", "old", "version",
    "chahiye", "chahiya", "dila", "dilado", "dedo", "mangta", "manga",
    "are", "bahut", "main", "tum", "hum", "ham", "tera", "teri",
    "tumhara", "tumhari", "aap", "aapka", "aapki", "need", "yaar",
    "the", "a", "an", "is", "am", "are", "was", "were", "be", "been",
    "and", "or", "but", "if", "so", "for", "of", "to", "in", "on", "at",
    "by", "with", "from", "this", "that", "it", "as", "not", "no", "yes",
    "have", "has", "had", "will", "would", "could", "should", "can",
    "just", "only", "also", "there", "here", "now", "then", "about",
    "into", "than", "them", "they", "these", "those", "some", "any", "all",
    "more", "most", "other", "such", "own", "same", "few",
    "do", "does", "did", "doing", "get", "got", "getting", "going", "go",
    "make", "made", "take", "took", "came", "come", "give", "gave",
    "already", "uploaded", "done", "finished", "complete",
})


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
def init_db() -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS channels (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id      TEXT NOT NULL UNIQUE,
            channel_title   TEXT,
            added_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS channel_posts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id  INTEGER NOT NULL,
            chat_id     INTEGER NOT NULL,
            app_name    TEXT,
            full_text   TEXT,
            link        TEXT,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_app_name ON channel_posts(app_name)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_full_text ON channel_posts(full_text)")
    conn.commit()

    if CHANNEL_ID_ENV:
        for cid in CHANNEL_ID_ENV.split(","):
            cid = cid.strip()
            if cid:
                conn.execute("INSERT OR IGNORE INTO channels (channel_id) VALUES (?)", (cid,))
    if CHANNEL_USERNAME:
        for uname in CHANNEL_USERNAME.split(","):
            uname = uname.strip()
            if uname:
                conn.execute("INSERT OR IGNORE INTO channels (channel_id) VALUES (?)", (uname,))
    conn.commit()
    conn.close()


def get_channels() -> list:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.execute("SELECT channel_id, channel_title FROM channels ORDER BY added_at")
    channels = [{"id": r[0], "title": r[1]} for r in cursor.fetchall()]
    conn.close()
    return channels


def add_channel(channel_id: str) -> bool:
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("INSERT INTO channels (channel_id) VALUES (?)", (channel_id,))
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        conn.close()
        return False


def remove_channel(channel_id: str) -> bool:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.execute("DELETE FROM channels WHERE channel_id = ?", (channel_id,))
    conn.commit()
    removed = cursor.rowcount > 0
    conn.close()
    return removed


def update_channel_title(channel_id: str, title: str):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE channels SET channel_title = ? WHERE channel_id = ?", (title, channel_id))
    conn.commit()
    conn.close()


def store_post(message_id, chat_id, app_name, full_text, link, created_at=None):
    conn = sqlite3.connect(DB_PATH)
    if created_at:
        conn.execute(
            "INSERT OR REPLACE INTO channel_posts "
            "(message_id, chat_id, app_name, full_text, link, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (message_id, chat_id, app_name, full_text, link, created_at))
    else:
        conn.execute(
            "INSERT OR REPLACE INTO channel_posts "
            "(message_id, chat_id, app_name, full_text, link) VALUES (?, ?, ?, ?, ?)",
            (message_id, chat_id, app_name, full_text, link))
    conn.commit()
    conn.close()


def search_by_app_name(query: str, limit: int = 5) -> list:
    conn = sqlite3.connect(DB_PATH)
    query_clean = query.strip().lower().replace(" ", "")

    cursor = conn.execute(
        "SELECT app_name, full_text, link, message_id FROM channel_posts "
        "WHERE LOWER(REPLACE(app_name, ' ', '')) = ? ORDER BY created_at DESC",
        (query_clean,))
    results = [{"app_name": r[0], "text": r[1], "link": r[2], "message_id": r[3]} for r in cursor.fetchall()]

    if not results and len(query.strip()) >= 4:
        like_query = f"%{query.strip().lower()}%"
        cursor = conn.execute(
            "SELECT app_name, full_text, link, message_id FROM channel_posts "
            "WHERE LOWER(app_name) LIKE ? ORDER BY created_at DESC",
            (like_query,))
        results = [{"app_name": r[0], "text": r[1], "link": r[2], "message_id": r[3]} for r in cursor.fetchall()]

    conn.close()

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
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.execute("SELECT DISTINCT app_name FROM channel_posts WHERE app_name IS NOT NULL ORDER BY app_name")
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
    channels = get_channels()
    for ch in channels:
        ch_id = ch["id"]
        if not ch_id.startswith("-"):
            return f"https://t.me/{ch_id}/{message_id}"
    if chat_id < 0:
        positive_id = str(chat_id).replace("-100", "", 1)
        return f"https://t.me/c/{positive_id}/{message_id}"
    return f"https://t.me/c/{chat_id}/{message_id}"


# ---------------------------------------------------------------------------
# Gemini AI
# ---------------------------------------------------------------------------
_gemini_model = None
_gemini_disabled_until = 0  # timestamp; 0 = not disabled
_gemini_cache = {}  # simple in-memory cache: {message_text_lower: (app_name, timestamp)}
_GEMINI_CACHE_TTL = 300  # 5 minutes
_GEMINI_COOLDOWN = 60  # seconds to disable Gemini after a 429


def _gemini_available() -> bool:
    """Check if Gemini is available (not disabled due to rate limiting)."""
    if not _gemini_model:
        return False
    if _gemini_disabled_until and time.time() < _gemini_disabled_until:
        return False
    return True


def _disable_gemini_temporarily():
    """Disable Gemini for a cooldown period after rate limit error."""
    global _gemini_disabled_until
    _gemini_disabled_until = time.time() + _GEMINI_COOLDOWN
    logger.warning("⏳ Gemini disabled for %d seconds due to rate limit.", _GEMINI_COOLDOWN)


def _test_model(genai, model_name):
    """Test if a model works by making a simple API call."""
    try:
        test_model = genai.GenerativeModel(model_name)
        test_response = test_model.generate_content("Respond with OK")
        if test_response and test_response.text:
            return True
    except Exception:
        pass
    return False


def init_gemini():
    """Initialize Gemini AI model. Uses list_models() first (free), then one test call."""
    global _gemini_model
    if not GEMINI_API_KEY:
        logger.info("GEMINI_API_KEY not set — AI features disabled, using fallback.")
        return False
    try:
        import google.generativeai as genai
        genai.configure(api_key=GEMINI_API_KEY)

        preferred_models = [
            "gemini-2.0-flash",
            "gemini-1.5-flash",
            "gemini-1.5-flash-latest",
            "gemini-flash-latest",
            "gemini-2.0-flash-lite",
            "gemini-2.5-flash",
            "gemini-2.5-flash-lite",
            "gemini-1.5-pro",
            "gemini-1.5-pro-latest",
        ]

        # Step 1: Use list_models() — this is FREE, doesn't consume generate_content quota
        available_models = {}
        try:
            for m in genai.list_models():
                # supported_generation_methods items can be strings OR objects
                methods = m.supported_generation_methods
                method_names = []
                for method in methods:
                    if isinstance(method, str):
                        method_names.append(method)
                    elif hasattr(method, 'name'):
                        method_names.append(method.name)
                    else:
                        method_names.append(str(method))

                if "generateContent" in method_names:
                    available_models[m.name] = True
            logger.info("Found %d models supporting generateContent via list_models()", len(available_models))
        except Exception as list_err:
            logger.warning("list_models() failed: %s — will try preferred names directly.", list_err)

        # Step 2: Pick the best preferred model that's available (or just try them all)
        selected_model = None

        # First try preferred models that are in the available list
        for model_name in preferred_models:
            if not available_models or model_name in available_models:
                selected_model = model_name
                logger.info("Selected model (from list): %s", model_name)
                break

        # If no preferred model matched, use any available model
        if not selected_model and available_models:
            for name in available_models:
                if "flash" in name.lower() or "lite" in name.lower():
                    selected_model = name
                    logger.info("Selected model (fallback from list): %s", name)
                    break

        # Last resort: just use the first preferred name
        if not selected_model:
            selected_model = preferred_models[0]
            logger.info("Selected model (default): %s", selected_model)

        # Step 3: Initialize the model — NO test call (saves quota!)
        _gemini_model = genai.GenerativeModel(
            selected_model,
            system_instruction=(
                "You are an app name extractor bot for a Telegram group. "
                "Given a message from a user, extract the app name they are looking for. "
                "Respond with ONLY the app name, nothing else. "
                "If the message is NOT about searching/requesting an app, respond with 'NONE'. "
                "Handle spelling mistakes, Hinglish, and messy sentences. "
                "IMPORTANT: Normal conversation like 'hello', 'thanks', 'ok', "
                "'ab nhi ho payega', 'me hi hu', 'kaise ho', 'already uploaded' "
                "should return NONE. "
                "But if someone mentions an app name anywhere in a long sentence, extract it. "
                "Examples:\n"
                "Input: 'bhai remini ka apk update krdo pls' → Output: Remini\n"
                "Input: 'bhai please yaar ek app ki need hai wo dedo ke bhot din se "
                "aapko bol rha hu aapne nhi suna mujhe remini dedo' → Output: Remini\n"
                "Input: 'I stream flare apk chahiye' → Output: I Stream Flare\n"
                "Input: 'capcut mod dedo bhai' → Output: CapCut\n"
                "Input: 'hello kaise ho' → Output: NONE\n"
                "Input: 'reemni' → Output: Remini\n"
                "Input: 'cupcut' → Output: CapCut\n"
                "Input: 'tirculler' → Output: Truecaller\n"
                "Input: '#QuickTv' → Output: QuickTv\n"
                "Input: 'ab nhi ho payega' → Output: NONE\n"
                "Input: 'me hi hu' → Output: NONE\n"
                "Input: 'already uploaded' → Output: NONE\n"
                "Input: 'are grok dedo bahut phle dia tha' → Output: NONE\n"
                "Input: 'ok bhai thanks' → Output: NONE\n"
                "Input: 'mujhe pw app chahiye bhai' → Output: PW\n"
                "Input: 'bhai ek gaming app dila do' → Output: NONE\n"
                "Input: 'pocket fm chahiye' → Output: Pocket Fm\n"
            ),
        )

        logger.info("✅ Gemini AI initialized with model: %s (no test call — saving quota)", selected_model)
        return True

    except Exception as e:
        logger.error("Failed to initialize Gemini AI: %s", e)
        return False


async def gemini_extract_app_name(message_text: str) -> str:
    if not _gemini_available():
        return extract_app_name_from_sentence(message_text)

    # Check cache first
    cache_key = message_text.strip().lower()
    if cache_key in _gemini_cache:
        cached_name, cached_time = _gemini_cache[cache_key]
        if time.time() - cached_time < _GEMINI_CACHE_TTL:
            logger.info("Gemini cache hit: '%s' → '%s'", message_text, cached_name)
            return cached_name

    try:
        def call_gemini():
            response = _gemini_model.generate_content(
                f"Extract the app name from this message:\n{message_text}")
            return response.text.strip()

        result = await asyncio.wait_for(asyncio.to_thread(call_gemini), timeout=15.0)
        result = result.strip().strip('"').strip("'").strip()

        # Cache the result
        _gemini_cache[cache_key] = (result, time.time())

        if result.upper() == "NONE" or not result or len(result) < 2:
            logger.info("Gemini said NONE for: '%s'", message_text)
            return ""

        logger.info("Gemini extracted: '%s' from '%s'", result, message_text)
        return result
    except asyncio.TimeoutError:
        logger.warning("Gemini timed out, falling back.")
        return extract_app_name_from_sentence(message_text)
    except Exception as e:
        error_str = str(e)
        if "429" in error_str or "quota" in error_str.lower():
            _disable_gemini_temporarily()
            logger.warning("Gemini rate limited — disabled for %d seconds.", _GEMINI_COOLDOWN)
        else:
            logger.warning("Gemini failed (%s), falling back.", e)
        return extract_app_name_from_sentence(message_text)


async def gemini_fuzzy_search(app_name: str, db_results: list) -> list:
    if not _gemini_available() or not db_results:
        return db_results
    try:
        app_names_in_db = [r["app_name"] for r in db_results if r["app_name"]]
        if not app_names_in_db:
            return db_results

        def call_gemini():
            prompt = f"The user searched for: '{app_name}'\nAvailable apps:\n"
            for i, name in enumerate(app_names_in_db, 1):
                prompt += f"{i}. {name}\n"
            prompt += "\nWhich is the best match? Respond with ONLY the app name, or 'NONE'."
            return _gemini_model.generate_content(prompt).text.strip()

        result = await asyncio.wait_for(asyncio.to_thread(call_gemini), timeout=15.0)
        result = result.strip().strip('"').strip("'").strip()

        if result.upper() == "NONE":
            return []
        for post in db_results:
            if post["app_name"] and post["app_name"].lower() == result.lower():
                return [post]
        return db_results
    except Exception as e:
        if "429" in str(e) or "quota" in str(e).lower():
            _disable_gemini_temporarily()
        else:
            logger.warning("Gemini fuzzy search failed: %s", e)
        return db_results


# ---------------------------------------------------------------------------
# Text extraction & filtering
# ---------------------------------------------------------------------------
def extract_hashtags(text: str) -> list:
    matches = HASHTAG_PATTERN.findall(text)
    return [m.strip() for m in matches if m.strip() and len(m.strip()) >= 2]


def extract_text_from_message(message) -> str:
    if message.text:
        return message.text
    if message.caption:
        return message.caption
    return ""


def extract_app_name_from_sentence(text: str) -> str:
    """Fallback heuristic — stricter to avoid false positives."""
    text = text.strip()
    hashtags = extract_hashtags(text)
    if hashtags:
        return hashtags[0]

    # Check for non-search phrases
    text_lower = text.lower().strip()
    for phrase in NON_SEARCH_PHRASES:
        if phrase in text_lower:
            return ""

    cleaned = re.sub(r"[^\w\s]", " ", text)
    words = cleaned.split()
    # Filter out noise words and short words
    app_words = [w for w in words if w.lower() not in NOISE_WORDS and len(w) >= 3]
    if not app_words:
        return ""

    # If only one meaningful word, return it
    if len(app_words) == 1:
        return app_words[0]

    # If multiple words, check if they could be a multi-word app name
    # But be conservative — only join if they're adjacent in original text
    return " ".join(app_words[:3])  # max 3 words for app name


def should_process_message(text: str, gemini_available: bool) -> bool:
    text = text.strip()
    if not text or len(text) < 2:
        return False

    # Always process hashtags
    if HASHTAG_PATTERN.search(text):
        return True

    # Check for non-search phrases first
    text_lower = text.lower().strip()
    for phrase in NON_SEARCH_PHRASES:
        if phrase in text_lower:
            return False

    if len(text.split()) == 1:
        word = text.strip().lower().strip(".,!?;:'\"")
        if word in QUICK_SKIP or len(word) < 3:
            return False
        return True

    if gemini_available and _gemini_available():
        # Gemini is active — let it decide
        words = text.split()
        if len(words) <= 2:
            all_noise = all(w.lower().strip(".,!?;:'\"") in QUICK_SKIP or
                           w.lower().strip(".,!?;:'\"") in NOISE_WORDS
                           for w in words)
            if all_noise:
                return False
        return True
    else:
        # Gemini NOT available — use strict heuristic
        text_lower = text.lower()
        app_keywords = {"apk", "app", "mod", "update", "link", "download",
                        "latest", "version", "chahiye", "chahiya", "dila",
                        "dilado", "bhejo", "dena", "dedo", "krdo", "karo",
                        "mangta", "manga", "mango"}
        words_set = set(re.sub(r"[^\w\s]", " ", text_lower).split())
        if app_keywords & words_set:
            return True

        word_count = len(text.split())
        if word_count == 2:
            non_noise = [w for w in text.split()
                        if w.lower().strip(".,!?;:'\"") not in NOISE_WORDS
                        and len(w.strip(".,!?;:'\"")) >= 3]
            return bool(non_noise)
        return False


# ---------------------------------------------------------------------------
# Auto-import
# ---------------------------------------------------------------------------
async def import_channel_history(channel_target):
    if not SESSION_STRING or not API_ID or not API_HASH:
        return 0, 0
    try:
        from telethon import TelegramClient
        from telethon.sessions import StringSession
    except ImportError:
        return 0, 0

    imported = 0
    skipped = 0
    try:
        target_resolved = int(channel_target)
    except ValueError:
        target_resolved = channel_target

    client = None
    try:
        client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
        await client.start()
        entity = await client.get_entity(target_resolved)
        channel_title = getattr(entity, 'title', str(channel_target))
        update_channel_title(str(channel_target), channel_title)
        logger.info("Importing from: %s", channel_title)

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
                logger.info("[%s] %d posts...", channel_title, imported)

        logger.info("✅ [%s] Import: %d imported, %d skipped", channel_title, imported, skipped)
    except Exception as e:
        logger.error("Import failed for %s: %s", channel_target, e)
    finally:
        if client:
            try:
                await client.disconnect()
            except Exception:
                pass
    return imported, skipped


async def auto_import_all_channels():
    channels = get_channels()
    if not channels:
        return
    total = 0
    for ch in channels:
        imported, _ = await import_channel_history(ch["id"])
        total += imported
    logger.info("✅ All channels imported! Total: %d posts", total)


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------
def is_owner(update: Update) -> bool:
    if not OWNER_ID:
        return True
    return update.effective_user.id == OWNER_ID


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    count = get_post_count()
    channels = get_channels()
    ai_status = "✅ Enabled" if _gemini_available() else "❌ Disabled (quota/fallback)"
    text = (
        "👋 *Hello!*\n\n"
        "I'm a *MODAPPSKING Search Bot* with AI.\n\n"
        "📋 *How to use:*\n"
        "• Type an app name and I'll find it in the channel\n"
        "• You can use `#AppName` or just type the name\n"
        "• Spelling mistakes are OK — AI will understand!\n"
        "• Long sentences are OK too — just mention the app name\n\n"
        "✨ *Examples:*\n"
        "• `#QuickTv`\n"
        "• `remini`\n"
        "• `bhai capcut ka mod dila do`\n"
        "• `reemni` (spelling mistake — AI will fix!)\n\n"
        "📌 I always give the *latest* link for each app.\n"
        f"🤖 AI: {ai_status}\n"
        f"📚 Currently tracking *{count}* channel posts.\n"
        f"📺 Configured channels: *{len(channels)}*"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    count = get_post_count()
    channels = get_channels()
    ai_status = "✅ Enabled" if _gemini_available() else "❌ Disabled (quota/fallback)"
    channel_list = "\n".join(f"• {ch['title'] or ch['id']}" for ch in channels) or "None"
    await update.message.reply_text(
        f"📊 *MODAPPSKING Search Bot Statistics*\n\n"
        f"📚 Total channel posts: *{count}*\n"
        f"🤖 AI: {ai_status}\n"
        f"📺 Channels ({len(channels)}):\n{channel_list}",
        parse_mode="Markdown")


async def addchannel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_owner(update):
        await update.message.reply_text("❌ Only the bot owner can add channels.")
        return
    if not context.args:
        await update.message.reply_text(
            "📋 *Add Channel*\n\nUsage: `/addchannel <channel_id>`\n\n"
            "Example: `/addchannel -1001234567890`", parse_mode="Markdown")
        return
    channel_id = context.args[0].strip()
    channels = get_channels()
    if any(ch["id"] == channel_id for ch in channels):
        await update.message.reply_text(f"⚠️ Channel `{channel_id}` already configured.", parse_mode="Markdown")
        return
    if add_channel(channel_id):
        await update.message.reply_text(f"✅ Channel `{channel_id}` added!\n⏳ Importing...", parse_mode="Markdown")
        def run_import():
            asyncio.run(import_channel_history(channel_id))
        threading.Thread(target=run_import, daemon=True).start()
    else:
        await update.message.reply_text(f"❌ Failed to add channel.")


async def listchannels_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    channels = get_channels()
    if not channels:
        await update.message.reply_text("📺 No channels configured.\nUse `/addchannel <id>`.", parse_mode="Markdown")
        return
    lines = ["📺 *Configured Channels:*\n"]
    for i, ch in enumerate(channels, 1):
        lines.append(f"{i}. *{ch['title'] or 'Unknown'}*\n   ID: `{ch['id']}`")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def removechannel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_owner(update):
        await update.message.reply_text("❌ Only the bot owner can remove channels.")
        return
    if not context.args:
        await update.message.reply_text("Usage: `/removechannel <channel_id>`", parse_mode="Markdown")
        return
    channel_id = context.args[0].strip()
    if remove_channel(channel_id):
        await update.message.reply_text(f"✅ Channel `{channel_id}` removed.")
    else:
        await update.message.reply_text(f"❌ Channel not found.")


async def import_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not SESSION_STRING:
        await update.message.reply_text("❌ Import not available.")
        return
    await update.message.reply_text("⏳ Importing all channel history...")
    def run_import():
        asyncio.run(auto_import_all_channels())
    threading.Thread(target=run_import, daemon=True).start()
    await update.message.reply_text(f"✅ Import started! Current: *{get_post_count()}* posts.", parse_mode="Markdown")


async def channel_post_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
    app_name = hashtags[0] if hashtags else text[:50]
    store_post(message_id, chat_id, app_name, text, link)


async def find_app(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return

    message_text = update.message.text
    gemini_on = _gemini_available()

    if not should_process_message(message_text, gemini_on):
        return

    app_query = await gemini_extract_app_name(message_text)

    if not app_query or len(app_query) < 2:
        return

    logger.info("Searching: '%s' (from: '%s')", app_query, message_text)

    results = search_by_app_name(app_query, limit=5)

    if not results and gemini_on:
        logger.info("No exact match — Gemini fuzzy search...")
        all_names = get_all_app_names()
        if all_names:
            broad_results = []
            for name in all_names[:50]:
                if app_query.lower().split()[0] in name.lower():
                    conn = sqlite3.connect(DB_PATH)
                    cursor = conn.execute(
                        "SELECT app_name, full_text, link, message_id "
                        "FROM channel_posts WHERE LOWER(app_name) = ? "
                        "ORDER BY created_at DESC LIMIT 1", (name.lower(),))
                    for r in cursor.fetchall():
                        broad_results.append({"app_name": r[0], "text": r[1], "link": r[2], "message_id": r[3]})
                    conn.close()
            if broad_results:
                results = await gemini_fuzzy_search(app_query, broad_results)

    if not results:
        if HASHTAG_PATTERN.search(message_text):
            await update.message.reply_text(f"❌ No match for *{escape(app_query)}*.", parse_mode="Markdown")
        return

    if len(results) == 1:
        post = results[0]
        preview = (post["text"] or "")[:120]
        if len(post["text"] or "") > 120:
            preview += "..."
        reply = f"📱 *{escape(post['app_name'] or app_query)}*\n\n📝 {escape(preview)}\n\n🔗 [Open Post]({post['link']})"
        await update.message.reply_text(reply, parse_mode="Markdown", disable_web_page_preview=False)
    else:
        lines = [f"📱 *Found {len(results)} matches for* `{escape(app_query)}`:\n"]
        for i, post in enumerate(results, 1):
            preview = (post["text"] or "")[:60]
            if len(post["text"] or "") > 60:
                preview += "..."
            lines.append(f"{i}. *{escape(post['app_name'] or 'Unknown')}*\n   {escape(preview)}\n   🔗 [Open]({post['link']})")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown", disable_web_page_preview=True)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Exception: %s", context.error)


async def post_init(application: Application) -> None:
    init_gemini()
    count = get_post_count()
    if count == 0:
        logger.info("Database is empty — running auto-import...")
        await auto_import_all_channels()
    else:
        logger.info("Database has %d posts — skipping auto-import.", count)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    init_db()
    threading.Thread(target=start_keep_alive, args=(PORT,), daemon=True).start()
    threading.Thread(target=self_ping, daemon=True).start()

    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", start_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("import", import_command))
    app.add_handler(CommandHandler("addchannel", addchannel_command))
    app.add_handler(CommandHandler("listchannels", listchannels_command))
    app.add_handler(CommandHandler("removechannel", removechannel_command))
    app.add_handler(MessageHandler(filters.UpdateType.CHANNEL_POSTS, channel_post_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.GROUPS, find_app))
    app.add_error_handler(error_handler)

    logger.info("MODAPPSKING Search Bot is starting... Press Ctrl+C to stop.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
