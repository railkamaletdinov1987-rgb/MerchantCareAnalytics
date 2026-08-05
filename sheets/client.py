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

    def append_case(self, case_data: list):
        ws = self.get_worksheet("Cases")
        ws.append_row(case_data, value_input_option="USER_ENTERED")
        logger.info(f"Добавлен Case: {case_data[0]}")

    def append_message(self, row: list):
        """Все сообщения мерчантов (нагрузка)"""
        ws = self.get_worksheet("Messages")
        ws.append_row(row, value_input_option="USER_ENTERED")

    def get_all_cases(self):
        ws = self.get_worksheet("Cases")
        return ws.get_all_records()

    def get_all_messages(self):
        try:
            ws = self.get_worksheet("Messages")
            return ws.get_all_records()
        except Exception:
            return []

    def get_employees(self):
        ws = self.get_worksheet("Employees")
        return ws.get_all_records()

    def get_groups(self):
        ws = self.get_worksheet("Groups")
        return ws.get_all_records()

    def get_lunch(self):
        try:
            ws = self.get_worksheet("Dashboard")
            start = ws.acell("B1").value or ""
            end = ws.acell("B2").value or ""
            return start.strip(), end.strip()
        except Exception as e:
            logger.error(f"Ошибка чтения обеда: {e}")
            return "", ""

    def set_lunch_start(self, value: str):
        ws = self.get_worksheet("Dashboard")
        ws.update_acell("B1", value)
        ws.update_acell("B2", "")

    def set_lunch_end(self, value: str):
        ws = self.get_worksheet("Dashboard")
        ws.update_acell("B2", value)


sheets = SheetsClient()