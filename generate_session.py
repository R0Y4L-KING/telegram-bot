"""
Session String Generator (Telethon)
====================================
Run this script ONCE on your local computer to generate a session string.
This session string allows the bot to read channel history (bots can't
read history directly, so we use your user account for the import).

Usage:
    pip install telethon
    python generate_session.py

You will need:
    - API_ID and API_HASH from https://my.telegram.org
    - Your Telegram phone number (with country code, e.g. +91...)
    - A verification code that Telegram will send you
"""

from telethon.sync import TelegramClient
from telethon.sessions import StringSession

print("=" * 60)
print("  Session String Generator (Telethon)")
print("=" * 60)
print()

api_id = int(input("Enter your API_ID: ").strip())
api_hash = input("Enter your API_HASH: ").strip()
phone_number = input("Enter your phone number (with country code, e.g. +91...): ").strip()

print()
print("Connecting to Telegram...")
print("You will receive a verification code in your Telegram app.")
print()

client = TelegramClient(
    StringSession(),
    api_id,
    api_hash,
)

client.start(phone=phone_number)

session_string = client.session.save()

print()
print("=" * 60)
print("✅ Session string generated successfully!")
print("=" * 60)
print()
print("Copy the ENTIRE string below (including everything between the quotes)")
print("and add it to your Render environment variables as SESSION_STRING:")
print()
print(session_string)
print()
print("=" * 60)
print("⚠️  Make sure you copy the ENTIRE string — it is very long!")
print("=" * 60)

client.disconnect()
