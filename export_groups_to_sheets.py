import asyncio
from loguru import logger
from telegram.client import telegram_service
from sheets.client import sheets

async def main():
    logger.info("=== Выгрузка групп в Google Sheets ===")

    # 1. Подключаемся к Google Sheets
    if not sheets.connect():
        logger.error("Не удалось подключиться к Google Sheets")
        return

    # 2. Подключаемся к Telegram
    client = await telegram_service.start()
    dialogs = await telegram_service.get_dialogs()

    # 3. Собираем только группы
    groups = []
    for dialog in dialogs:
        if dialog.is_group or dialog.is_channel:
            groups.append(dialog.name)

    # Убираем дубликаты и сортируем
    groups = sorted(set(groups))
    logger.info(f"Найдено уникальных групп: {len(groups)}")

    # 4. Получаем лист Groups
    ws = sheets.get_worksheet("Groups")

    # Очищаем старые данные (кроме заголовка)
    ws.clear()
    ws.append_row(["ID", "Merchant", "Telegram Group", "Ответственный"])

    # 5. Записываем группы
    rows = []
    for i, name in enumerate(groups, 1):
        rows.append([
            i,          # ID
            "",         # Merchant (пока пусто — заполнишь вручную)
            name,       # Telegram Group (точное название)
            ""          # Ответственный
        ])

    # Записываем всё сразу (быстрее)
    ws.append_rows(rows, value_input_option="USER_ENTERED")

    logger.success(f"Успешно записано {len(groups)} групп в лист Groups")
    logger.info("Теперь открой таблицу и заполни колонки Merchant и Ответственный")

    await telegram_service.disconnect()

if __name__ == "__main__":
    asyncio.run(main())