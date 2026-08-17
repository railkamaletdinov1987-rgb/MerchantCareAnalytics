import asyncio
import sys
from loguru import logger
from telethon import events

from telegram.client import telegram_service
from telegram.handler import MessageHandler
from sheets.client import sheets


RECONNECT_DELAY_SEC = 15
MAX_DELAY_SEC = 120

_handler_instance = None
_handler_registered = False


async def _on_new_message(event):
    if _handler_instance is None:
        return
    await _handler_instance.handle_new_message(event)


async def run_once():
    global _handler_instance, _handler_registered

    logger.info("=== Запуск слушателя сообщений ===")

    sheets.connect()
    logger.success("Google Sheets подключен")

    await telegram_service.start()
    tg_client = telegram_service.client

    handler = MessageHandler(tg_client)
    handler.load_references()
    _handler_instance = handler

    # Догрузка (catchup) временно отключена — меньше таймаутов
    logger.info("Догрузка истории пропущена (режим без catchup)")

    if not _handler_registered:
        tg_client.add_event_handler(_on_new_message, events.NewMessage)
        _handler_registered = True
        logger.success("Обработчик сообщений зарегистрирован")
    else:
        logger.info("Обработчик уже зарегистрирован — пропускаем")

    logger.success("Слушатель запущен. Ждём сообщения... (Ctrl+C для остановки)")

    await tg_client.run_until_disconnected()
    logger.warning("Соединение с Telegram закрыто")


async def main():
    delay = RECONNECT_DELAY_SEC

    while True:
        try:
            await run_once()
            delay = RECONNECT_DELAY_SEC
            logger.warning(f"Переподключение через {delay} сек...")
        except KeyboardInterrupt:
            logger.info("Остановка по Ctrl+C")
            break
        except Exception as e:
            logger.error(f"Сбой слушателя: {e}")
            logger.warning(f"Переподключение через {delay} сек...")

        try:
            await telegram_service.disconnect()
        except Exception:
            pass

        await asyncio.sleep(delay)
        delay = min(int(delay * 1.5), MAX_DELAY_SEC)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Выход")
        sys.exit(0)