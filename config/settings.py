from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Telegram
    telegram_api_id: Optional[int] = None
    telegram_api_hash: Optional[str] = None
    telegram_phone: Optional[str] = None
    telegram_session_name: str = "merchant_care"

    # Google Sheets
    google_sheets_id: str
    google_credentials_file: str = "config/credentials.json"

    # App
    timezone: str = "Asia/Tashkent"
    poll_interval_seconds: int = 30
    sla_minutes: int = 20
    lunch_start: Optional[str] = None
    lunch_end: Optional[str] = None

    # Dashboard
    dashboard_host: str = "0.0.0.0"
    dashboard_port: int = 8000
    debug: bool = True
    dashboard_title: str = "Merchant Care Analytics"

    # Доступ
    dashboard_view_password: Optional[str] = None
    dashboard_admin_password: Optional[str] = None

    @property
    def credentials_path(self) -> Path:
        return BASE_DIR / self.google_credentials_file

    @property
    def session_path(self) -> Path:
        return BASE_DIR / "data" / self.telegram_session_name


settings = Settings()