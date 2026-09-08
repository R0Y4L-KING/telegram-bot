# Telegram Channel Search Bot

A Telegram bot that monitors a channel for posts and helps group users find apps by name.

## How It Works

1. **Bot is added as admin** to a Telegram channel
2. Every channel post with a `#AppName` tag is stored in a database
3. When a user in a group types an app name, the bot searches the database
4. Bot replies with a **direct link** to the **latest** matching channel post

## Features

- ✅ Automatic channel post indexing (new posts)
- ✅ Import existing channel history (`import_history.py`)
- ✅ Single word, hashtag, and full sentence search
- ✅ Smart noise word filtering (Hindi + English)
- ✅ Returns only the **latest** post per app (old/expired links skipped)
- ✅ Direct Telegram post links
- ✅ SQLite database (no external DB needed)

## Setup

### 1. Get a Bot Token
- Open Telegram and message [@BotFather](https://t.me/BotFather)
- Send `/newbot` and follow the instructions
- Copy the bot token

### 2. Get Telegram API Credentials
- Go to [my.telegram.org](https://my.telegram.org)
- Log in with your phone number
- Click **API Development Tools**
- Create a new app (any name)
- Copy the **API ID** and **API Hash**

### 3. Add Bot to Your Channel
- Go to your channel settings → Administrators
- Add the bot as an admin
- Give it permission to read/post messages

### 4. Add Bot to Your Group
- Add the bot to the group where users will search for apps
- Make sure it has permission to send messages

### 5. Configuration
```bash
# Clone the repo
git clone https://github.com/R0Y4L-KING/telegram-bot.git
cd telegram-bot

# Install dependencies
pip install -r requirements.txt

# Create .env file
cp .env.example .env
# Edit .env and add your BOT_TOKEN, API_ID, API_HASH
```

### 6. Get Channel Info
- **Public channel:** Set `CHANNEL_USERNAME` (without @)
- **Private channel:** Set `CHANNEL_ID` (forward a message from channel to [@userinfobot](https://t.me/userinfobot) to get the ID)

### 7. Import Existing Channel History (IMPORTANT)

If your channel already has posts, run this **once** before starting the bot:

```bash
python import_history.py
```

This will scan all your existing channel posts and store them in the database.
After this, the bot will automatically store new posts as they come in.

### 8. Run the Bot
```bash
python bot.py
```

## Usage

| Action | Example |
|--------|---------|
| Search by hashtag | Type `#QuickTv` in the group |
| Search by name | Type `remini` in the group |
| Search by sentence | Type `bhai remini ka apk update krdo pls` |
| Bot info | Send `/start` or `/help` |
| Database stats | Send `/stats` |

## Channel Post Format

Posts in the channel should contain a `#AppName` hashtag so the bot can identify them:

```
🟪 APK INFO :- #QuickTv Quick TV is India's next-gen HD streaming platform...
```

The bot extracts `#QuickTv` as the app name and uses it for searching.

## Requirements

- Python 3.10+
- Telegram Bot Token (from @BotFather)
- Telegram API ID + Hash (from my.telegram.org)
- Bot must be admin in the channel
- Bot must be member of the group

## Tech Stack

- **Bot:** `python-telegram-bot` (real-time monitoring + group search)
- **Import:** `pyrogram` (reading channel history)
- **Database:** SQLite (built-in)
- **Config:** `python-dotenv`

## License

MIT
