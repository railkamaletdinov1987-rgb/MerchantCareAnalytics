import asyncio
from loguru import logger
from telegram.client import telegram_service

async def main():
    logger.info("=== Получаем список всех групп ===")
    
    client = await telegram_service.start()
    
    dialogs = await telegram_service.get_dialogs()
    
    groups = []
    for dialog in dialogs:
        # Берём только группы и супергруппы
        if dialog.is_group or dialog.is_channel:
            groups.append(dialog.name)
    
    # Сортируем по алфавиту
    groups = sorted(set(groups))
    
    logger.info(f"Найдено групп/каналов: {len(groups)}")
    print("\n" + "="*50)
    print("СПИСОК ГРУПП:")
    print("="*50)
    
    for i, name in enumerate(groups, 1):
        print(f"{i}. {name}")
    
    # Сохраняем в файл
    with open("groups_list.txt", "w", encoding="utf-8") as f:
        for name in groups:
            f.write(name + "\n")
    
    logger.success(f"Список сохранён в файл groups_list.txt")
    
    await telegram_service.disconnect()

if __name__ == "__main__":
    asyncio.run(main())