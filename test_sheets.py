from datetime import datetime
from loguru import logger
from sheets.client import sheets

def main():
    logger.info("=== Тест подключения к Google Sheets ===")

    # Подключаемся
    if not sheets.connect():
        logger.error("Не удалось подключиться. Проверь credentials.json и доступ.")
        return

    # Проверяем листы
    try:
        worksheets = [ws.title for ws in sheets.spreadsheet.worksheets()]
        logger.info(f"Найденные листы: {worksheets}")
    except Exception as e:
        logger.error(f"Ошибка при чтении листов: {e}")
        return

    # Создаём тестовую запись в Cases
    now = datetime.now()
    test_case = [
        "TEST-001",                          # Case ID
        now.strftime("%d.%m.%Y"),            # Дата
        now.strftime("%H:%M:%S"),            # Время
        "ORIFLAME",                          # Merchant
        "ORIFLAME Support",                  # Group
        "TR000000",                          # Track
        now.strftime("%H:%M:%S"),            # First Response
        2,                                   # Response Time (минуты)
        "Тестовый сотрудник",                # Employee
        "Closed",                            # Status
        "OK",                                # SLA
        "No",                                # Reopened
    ]

    try:
        sheets.append_case(test_case)
        logger.success("Тестовая запись успешно добавлена в лист Cases!")
        logger.info("Открой таблицу и проверь — должна появиться строка TEST-001")
    except Exception as e:
        logger.error(f"Ошибка при записи: {e}")

if __name__ == "__main__":
    main()