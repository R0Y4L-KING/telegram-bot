# Telegram Channel Search Bot

A Telegram bot that monitors a channel for posts and helps group users find apps by name.

## How It Works

1. **Bot is added as admin** to a Telegram channel
2. Every new channel post is automatically **stored** in a database (text + direct link)
3. When a user in a group types an **app name** (single word like `remini`, `capcut`, `truecaller`), the bot searches the database
4. Bot replies with a **direct link** to the matching channel post

## Features

- ✅ Automatic channel post indexing
- ✅ Single-word search in groups
- ✅ Direct Telegram post links
- ✅ Multiple result support
- ✅ Smart filtering (ignores common chat words)
- ✅ SQLite database (no external DB needed)

## Setup

### 1. Get a Bot Token
- Open Telegram and message [@BotFather](https://t.me/BotFather)
- Send `/newbot` and follow the instructions
- Copy the bot token

### 2. Add Bot to Your Channel
- Go to your channel settings → Administrators
- Add the bot as an admin
- Give it permission to read messages

### 3. Add Bot to Your Group
- Add the bot to the group where users will search for apps
- Make sure it has permission to send messages

### 4. Configuration
```bash
# Clone the repo
git clone https://github.com/R0Y4L-KING/telegram-bot.git
cd telegram-bot

# Install dependencies
pip install -r requirements.txt

# Create .env file
cp .env.example .env
# Edit .env and add your BOT_TOKEN
```

### 5. Get Channel Info (optional)
- **Public channel:** Set `CHANNEL_USERNAME` (without @)
- **Private channel:** Set `CHANNEL_ID` (forward a message from channel to [@userinfobot](https://t.me/userinfobot) to get the ID)

### 6. Run the Bot
```bash
python bot.py
```

## Usage

| Action | Example |
|--------|---------|
| Search for an app | Type `remini` in the group |
| Bot info | Send `/start` or `/help` |
| Database stats | Send `/stats` |

## Requirements

- Python 3.10+
- Telegram Bot Token (from @BotFather)
- Bot must be admin in the channel
- Bot must be member of the group

## Tech Stack

- **Python** — `python-telegram-bot`
- **Database** — SQLite (built-in, no setup needed)
- **Config** — `python-dotenv`

## License

MIT
