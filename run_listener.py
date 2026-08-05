import asyncio
from loguru import logger
from telegram.client import telegram_service
from telegram.handler import MessageHandler
from telegram.catchup import CatchUp
from telegram.sync_groups import sync_new_groups
from sheets.client import sheets

async def main():
    logger.info("=== Запуск слушателя сообщений ===")

    if not sheets.connect():
        logger.error("Не удалось подключиться к Google Sheets")
        return

    client = await telegram_service.start()

    handler = MessageHandler(client)
    handler.load_references()

    # 1. Новые группы из Telegram → лист Groups
    await sync_new_groups(client)

    # После добавления групп перечитываем справочники
    handler.load_references()

    # 2. Догрузка истории (Open Cases + сообщения мерчантов)
    catchup = CatchUp(client, handler)
    await catchup.run()

    # 3. Онлайн-слушатель
    handler.register()

    logger.success("Слушатель запущен. Ждём сообщения... (Ctrl+C для остановки)")
    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())