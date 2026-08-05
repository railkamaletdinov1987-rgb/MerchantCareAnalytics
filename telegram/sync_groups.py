from loguru import logger
from sheets.client import sheets


async def sync_new_groups(client):
    """
    Находит новые группы в Telegram и добавляет их в лист Groups.
    Уже существующие не трогает.
    Новые добавляются с пустым Merchant → в работу не попадают,
    пока Merchant не заполните вручную.
    """
    logger.info("=== Синхронизация новых групп ===")

    if not sheets.connect():
        logger.error("Не удалось подключиться к Google Sheets")
        return 0

    existing = sheets.get_groups()
    existing_names = set()
    for g in existing:
        name = str(g.get("Telegram Group", "")).strip().lower()
        if name:
            existing_names.add(name)

    new_groups = []
    async for dialog in client.iter_dialogs():
        if not (dialog.is_group or dialog.is_channel):
            continue
        if not dialog.name:
            continue

        name = dialog.name.strip()
        if name.lower() in existing_names:
            continue

        new_groups.append(name)

    if not new_groups:
        logger.info("Новых групп не найдено")
        return 0

    ws = sheets.get_worksheet("Groups")
    all_values = ws.get_all_values()
    next_id = len(all_values)  # следующая строка после заголовка/данных

    rows = []
    for i, name in enumerate(sorted(new_groups), start=1):
        rows.append([
            next_id + i - 1,  # ID
            "",               # Merchant — заполнить вручную
            name,             # Telegram Group
            "",               # Ответственный
        ])

    ws.append_rows(rows, value_input_option="USER_ENTERED")
    logger.success(f"Добавлено новых групп: {len(new_groups)}")

    for name in sorted(new_groups):
        logger.info(f"  + {name}")

    return len(new_groups)