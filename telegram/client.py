from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from loguru import logger
from config.settings import settings


class TelegramService:
    def __init__(self):
        self.client = TelegramClient(
            str(settings.session_path),
            settings.telegram_api_id,
            settings.telegram_api_hash,
        )

    async def start(self):
        """Запуск и авторизация клиента"""
        await self.client.start(phone=settings.telegram_phone)
        me = await self.client.get_me()
        logger.success(f"Авторизован как: {me.first_name} (@{me.username})")
        return self.client

    async def get_dialogs(self):
        """Получить список всех чатов и групп"""
        dialogs = await self.client.get_dialogs()
        return dialogs

    async def disconnect(self):
        await self.client.disconnect()


telegram_service = TelegramService()