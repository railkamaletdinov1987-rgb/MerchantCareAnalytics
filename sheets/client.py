import time
import gspread
from google.oauth2.service_account import Credentials
from loguru import logger
from config.settings import settings


class SheetsClient:
    def __init__(self):
        self.scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        self.client = None
        self.spreadsheet = None

    def connect(self):
        try:
            creds = Credentials.from_service_account_file(
                str(settings.credentials_path),
                scopes=self.scopes,
            )
            self.client = gspread.authorize(creds)
            self.spreadsheet = self.client.open_by_key(settings.google_sheets_id)
            logger.success(f"Подключено к таблице: {self.spreadsheet.title}")
            return True
        except Exception as e:
            logger.error(f"Ошибка подключения к Google Sheets: {e}")
            return False

    def get_worksheet(self, name: str):
        return self.spreadsheet.worksheet(name)

    def _with_retry(self, func, *args, **kwargs):
        """Повтор при 429: ждём до 90 сек"""
        last_error = None
        for attempt in range(6):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                msg = str(e)
                last_error = e
                if "429" in msg or "Quota exceeded" in msg:
                    wait = 20 + attempt * 15  # 20, 35, 50, 65, 80, 95
                    logger.warning(
                        f"Лимит Sheets API, жду {wait} сек... "
                        f"(попытка {attempt + 1}/6)"
                    )
                    time.sleep(wait)
                    continue
                raise
        raise last_error

    def append_case(self, case_data: list):
        ws = self.get_worksheet("Cases")
        self._with_retry(ws.append_row, case_data, value_input_option="USER_ENTERED")
        logger.info(f"Добавлен Case: {case_data[0]}")
        time.sleep(1.2)

    def append_message(self, row: list):
        ws = self.get_worksheet("Messages")
        self._with_retry(ws.append_row, row, value_input_option="USER_ENTERED")
        time.sleep(1.2)

    def get_all_cases(self):
        ws = self.get_worksheet("Cases")
        result = self._with_retry(ws.get_all_records)
        time.sleep(0.5)
        return result

    def get_all_messages(self):
        try:
            ws = self.get_worksheet("Messages")
            result = self._with_retry(ws.get_all_records)
            time.sleep(0.5)
            return result
        except Exception:
            return []

    def get_employees(self):
        ws = self.get_worksheet("Employees")
        return self._with_retry(ws.get_all_records)

    def get_groups(self):
        ws = self.get_worksheet("Groups")
        return self._with_retry(ws.get_all_records)

    def get_lunch(self):
        try:
            ws = self.get_worksheet("Dashboard")
            start = self._with_retry(ws.acell, "B1").value or ""
            end = self._with_retry(ws.acell, "B2").value or ""
            return start.strip(), end.strip()
        except Exception as e:
            logger.error(f"Ошибка чтения обеда: {e}")
            return "", ""

    def set_lunch_start(self, value: str):
        ws = self.get_worksheet("Dashboard")
        self._with_retry(ws.update_acell, "B1", value)
        self._with_retry(ws.update_acell, "B2", "")

    def set_lunch_end(self, value: str):
        ws = self.get_worksheet("Dashboard")
        self._with_retry(ws.update_acell, "B2", value)


sheets = SheetsClient()