#!/usr/bin/env python3
"""Clear Telegram webhook to resolve polling conflicts."""

import asyncio
import sys
from telegram import Bot
from nanobot.config.loader import load_config


async def main():
    config = load_config()
    token = config.channels.telegram.token

    if not token:
        print("Error: Telegram token not configured")
        sys.exit(1)

    bot = Bot(token=token)

    print("Clearing webhook and pending updates...")
    result = await bot.delete_webhook(drop_pending_updates=True)

    if result:
        print("✓ Webhook cleared successfully")

        # Get bot info to verify connection
        me = await bot.get_me()
        print(f"✓ Bot verified: @{me.username}")
    else:
        print("✗ Failed to clear webhook")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
