import asyncio
from loguru import logger
from telegram.client import telegram_service

async def main():
    logger.info("=== Тест авторизации Telegram ===")
    
    try:
        client = await telegram_service.start()
        
        # Получаем список диалогов (групп)
        dialogs = await telegram_service.get_dialogs()
        
        logger.info(f"Найдено чатов/групп: {len(dialogs)}")
        logger.info("Первые 10 групп:")
        
        for i, dialog in enumerate(dialogs[:10]):
            logger.info(f"{i+1}. {dialog.name}")
            
        await telegram_service.disconnect()
        logger.success("Тест успешно завершён")
        
    except Exception as e:
        logger.error(f"Ошибка: {e}")

if __name__ == "__main__":
    asyncio.run(main())