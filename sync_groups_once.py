import asyncio
from loguru import logger
from telegram.client import telegram_service
from telegram.sync_groups import sync_new_groups
from sheets.client import sheets

async def main():
    if not sheets.connect():
        return
    client = await telegram_service.start()
    await sync_new_groups(client)
    await telegram_service.disconnect()

if __name__ == "__main__":
    asyncio.run(main())