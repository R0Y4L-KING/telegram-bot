"""
Session String Generator
========================
Run this script ONCE on your local computer to generate a session string.
This session string allows the bot to read channel history (bots can't
read history directly, so we use your user account for the import).

This script will NOT be run on Render — only locally.

Usage:
    python generate_session.py

You will need:
    - API_ID and API_HASH from https://my.telegram.org
    - Your Telegram phone number (with country code, e.g. +91...)
    - A verification code that Telegram will send you

Steps:
    1. pip install pyrogram tgcrypto
    2. python generate_session.py
    3. Enter API_ID, API_HASH, phone number when prompted
    4. Enter the verification code Telegram sends you
    5. Copy the session string and add it to Render as SESSION_STRING
"""

import asyncio
from pyrogram import Client


async def main():
    print("=" * 60)
    print("  Session String Generator")
    print("=" * 60)
    print()

    api_id = int(input("Enter your API_ID: ").strip())
    api_hash = input("Enter your API_HASH: ").strip()
    phone_number = input("Enter your phone number (with country code, e.g. +91...): ").strip()

    print()
    print("Connecting to Telegram...")
    print("You will receive a verification code in your Telegram app.")
    print()

    client = Client(
        "session_gen",
        api_id=api_id,
        api_hash=api_hash,
        in_memory=True,
    )

    await client.start(phone_number=phone_number)

    session_string = await client.export_session_string()

    await client.stop()

    print()
    print("=" * 60)
    print("✅ Session string generated successfully!")
    print("=" * 60)
    print()
    print("Copy the string below and add it to your Render environment")
    print("variables as SESSION_STRING:")
    print()
    print(session_string)
    print()
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
