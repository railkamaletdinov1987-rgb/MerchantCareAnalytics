from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo
import re
from loguru import logger
from telethon import events
from telethon.tl.types import User
from config.settings import settings
from sheets.client import sheets


class MessageHandler:
    def __init__(self, client):
        self.client = client
        self.employees = set()
        self.employee_display = {}
        self.employee_by_name = {}
        self.groups_map = {}
        self.groups_responsible = {}
        self.duty_operator = None
        self.sla_minutes = settings.sla_minutes
        self.tz = ZoneInfo("Asia/Tashkent")

    def load_references(self):
        employees_data = sheets.get_employees()
        self.employees = set()
        self.employee_display = {}
        self.employee_by_name = {}
        self.duty_operator = None

        for emp in employees_data:
            raw_username = str(emp.get("Telegram", "")).strip()
            name = str(emp.get("Сотрудник", "")).strip()

            if not raw_username:
                continue

            display = raw_username if raw_username.startswith("@") else "@" + raw_username
            key = display.lower()

            self.employees.add(key)
            self.employee_display[key] = display

            if name:
                self.employee_by_name[name.lower()] = display
            self.employee_by_name[key] = display
            self.employee_by_name[key.lstrip("@")] = display

            on_duty = str(emp.get("На смене", "")).strip().lower()
            if on_duty in ("да", "yes", "1", "true", "+"):
                self.duty_operator = display

        self.employees.add("@merchant_care_fargo")
        if "@merchant_care_fargo" not in self.employee_display:
            self.employee_display["@merchant_care_fargo"] = "@Merchant_Care_Fargo"

        logger.info(f"Загружено сотрудников: {len(self.employees)}")
        if self.duty_operator:
            logger.info(f"На смене (приоритет для @Merchant_Care_Fargo): {self.duty_operator}")
        else:
            logger.info("На смене: не указан → будет Ответственный группы")

        groups_data = sheets.get_groups()
        self.groups_map = {}
        self.groups_responsible = {}

        for g in groups_data:
            group_name = str(g.get("Telegram Group", "")).strip()
            merchant = str(g.get("Merchant", "")).strip()
            responsible = str(g.get("Ответственный", "")).strip()

            if not group_name or not merchant:
                continue

            gkey = group_name.lower()
            self.groups_map[gkey] = merchant

            if responsible:
                resp_key = responsible.lower()
                resolved = self.employee_by_name.get(resp_key)
                if not resolved and not resp_key.startswith("@"):
                    resolved = self.employee_by_name.get("@" + resp_key)
                if resolved:
                    self.groups_responsible[gkey] = resolved
                else:
                    disp = responsible if responsible.startswith("@") else "@" + responsible
                    self.groups_responsible[gkey] = disp

        logger.info(f"Активных групп (с Merchant): {len(self.groups_map)}")
        logger.info(f"Групп с ответственным: {len(self.groups_responsible)}")

    def is_employee(self, sender) -> bool:
        if not sender or not getattr(sender, "username", None):
            return False
        username = "@" + sender.username.lower()
        return username in self.employees

    def resolve_employee_name(self, sender, group_name: str) -> str:
        if not sender or not getattr(sender, "username", None):
            return "Unknown"

        username_key = "@" + sender.username.lower()

        if username_key != "@merchant_care_fargo":
            return self.employee_display.get(username_key, "@" + sender.username)

        if self.duty_operator:
            return self.duty_operator

        gkey = group_name.lower()
        responsible = self.groups_responsible.get(gkey)
        if responsible:
            return responsible

        return self.employee_display.get("@merchant_care_fargo", "@Merchant_Care_Fargo")

    def extract_track(self, text: str) -> str:
        if not text:
            return ""
        match = re.search(
            r"(TR\d{5,}|TEZ\d{5,}|[A-Z]{2,5}\d{6,}|\b\d{6,12}\b)",
            text.upper()
        )
        return match.group(0) if match else ""

    def extract_phone(self, text: str) -> str:
        if not text:
            return ""
        patterns = [
            r"\+998[\s\-]?\d{2}[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}",
            r"998[\s\-]?\d{2}[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}",
            r"\b\d{2}[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}\b",
            r"\b\d{9}\b",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return re.sub(r"[\s\-]", "", match.group(0))
        return ""

    def is_valid_request(self, text: str) -> bool:
        if not text:
            return False
        return bool(self.extract_track(text) or self.extract_phone(text))

    def get_work_bounds(self, dt: datetime):
        weekday = dt.weekday()
        if weekday == 6:
            return None, None
        if weekday == 5:
            return time(10, 0), time(18, 0)
        return time(10, 0), time(19, 0)

    def get_effective_start(self, case_dt: datetime) -> datetime:
        weekday = case_dt.weekday()
        t = case_dt.time()
        work_start, work_end = self.get_work_bounds(case_dt)

        if weekday == 6:
            next_dt = case_dt + timedelta(days=1)
            return next_dt.replace(hour=10, minute=0, second=0, microsecond=0)

        if weekday == 5 and work_end and t >= work_end:
            next_dt = case_dt + timedelta(days=2)
            return next_dt.replace(hour=10, minute=0, second=0, microsecond=0)

        if weekday < 5 and work_end and t >= work_end:
            next_dt = case_dt + timedelta(days=1)
            if next_dt.weekday() == 6:
                next_dt += timedelta(days=1)
            return next_dt.replace(hour=10, minute=0, second=0, microsecond=0)

        if work_start and t < work_start:
            return case_dt.replace(hour=10, minute=0, second=0, microsecond=0)

        return case_dt

    def working_minutes_between(self, start: datetime, end: datetime) -> int:
        if end <= start:
            return 0

        total = 0
        current = start

        while current.date() <= end.date():
            work_start_t, work_end_t = self.get_work_bounds(current)
            if work_start_t is None:
                current = datetime.combine(
                    current.date() + timedelta(days=1),
                    time(0, 0),
                    tzinfo=self.tz,
                )
                continue

            day_start = datetime.combine(current.date(), work_start_t, tzinfo=self.tz)
            day_end = datetime.combine(current.date(), work_end_t, tzinfo=self.tz)

            seg_start = max(start, day_start, current)
            seg_end = min(end, day_end)

            if seg_start < seg_end:
                minutes = int((seg_end - seg_start).total_seconds() / 60)
                total += max(0, minutes)

            current = datetime.combine(
                current.date() + timedelta(days=1),
                time(0, 0),
                tzinfo=self.tz,
            )

        return total

    def subtract_lunch(self, response_minutes: int, effective_start: datetime, response_dt: datetime) -> int:
        try:
            lunch_start_str, lunch_end_str = sheets.get_lunch()
            lunch_start_dt = None
            lunch_end_dt = None

            if lunch_start_str:
                lunch_start_dt = datetime.strptime(
                    lunch_start_str, "%d.%m.%Y %H:%M:%S"
                ).replace(tzinfo=self.tz)
            if lunch_end_str:
                lunch_end_dt = datetime.strptime(
                    lunch_end_str, "%d.%m.%Y %H:%M:%S"
                ).replace(tzinfo=self.tz)

            if lunch_start_dt and lunch_end_dt:
                overlap_start = max(effective_start, lunch_start_dt)
                overlap_end = min(response_dt, lunch_end_dt)
                if overlap_start < overlap_end:
                    lunch_mins = int((overlap_end - overlap_start).total_seconds() / 60)
                    response_minutes = max(0, response_minutes - lunch_mins)

            elif lunch_start_dt and not lunch_end_dt:
                overlap_start = max(effective_start, lunch_start_dt)
                if overlap_start < response_dt:
                    lunch_mins = int((response_dt - overlap_start).total_seconds() / 60)
                    response_minutes = max(0, response_minutes - lunch_mins)

        except Exception as e:
            logger.error(f"Ошибка учёта обеда: {e}")

        return response_minutes

    async def log_merchant_message(self, merchant, group_name, msg_date):
        """Любое сообщение мерчанта → лист Messages (нагрузка)"""
        now = msg_date.astimezone(self.tz)
        try:
            sheets.append_message([
                now.strftime("%d.%m.%Y"),
                now.strftime("%H:%M:%S"),
                merchant,
                group_name,
            ])
        except Exception as e:
            logger.error(f"Ошибка записи Messages: {e}")

    async def handle_new_message(self, event):
        try:
            chat = await event.get_chat()

            if isinstance(chat, User) or not getattr(chat, "title", None):
                return

            sender = await event.get_sender()
            text = event.message.text or ""
            msg_date = event.message.date

            chat_title = (chat.title or "").strip()
            if chat_title.lower() not in self.groups_map:
                return

            merchant = self.groups_map[chat_title.lower()]
            is_emp = self.is_employee(sender)

            logger.info(
                f"{'Сотрудник' if is_emp else 'Мерчант'} | "
                f"{chat_title} | {text[:60]}..."
            )

            if not is_emp:
                # Всегда считаем нагрузку
                await self.log_merchant_message(merchant, chat_title, msg_date)

                # Case — только с треком/телефоном
                if not self.is_valid_request(text):
                    logger.info("Сообщение учтено в Messages (без Case)")
                    return

                await self.create_case(
                    merchant=merchant,
                    group_name=chat_title,
                    text=text,
                    msg_date=msg_date,
                    sender=sender,
                )
            else:
                await self.process_employee_reply(
                    merchant=merchant,
                    group_name=chat_title,
                    text=text,
                    msg_date=msg_date,
                    sender=sender,
                )

        except Exception as e:
            logger.error(f"Ошибка обработки сообщения: {e}")

    async def create_case(self, merchant, group_name, text, msg_date, sender):
        now = msg_date.astimezone(self.tz)
        track = self.extract_track(text)
        phone = self.extract_phone(text)
        track_value = track if track else phone

        case_id = f"C-{now.strftime('%Y%m%d%H%M%S')}"

        case_data = [
            case_id,
            now.strftime("%d.%m.%Y"),
            now.strftime("%H:%M:%S"),
            merchant,
            group_name,
            track_value,
            "",
            "",
            "",
            "Open",
            "",
            "No",
        ]

        sheets.append_case(case_data)
        logger.success(
            f"Создан Case {case_id} | {merchant} | "
            f"{'Track: ' + track if track else 'Phone: ' + phone}"
        )

    async def process_employee_reply(self, merchant, group_name, text, msg_date, sender):
        username = self.resolve_employee_name(sender, group_name)

        all_cases = sheets.get_all_cases()

        open_case = None
        open_case_row = None

        for i, case in enumerate(all_cases):
            if (str(case.get("Group", "")).strip() == group_name and
                str(case.get("Status", "")).strip() == "Open"):
                open_case = case
                open_case_row = i + 2

        if not open_case:
            logger.info(f"Нет открытых Case в группе {group_name} для ответа {username}")
            return

        try:
            case_date = open_case.get("Дата", "")
            case_time = open_case.get("Время", "")

            case_dt = datetime.strptime(f"{case_date} {case_time}", "%d.%m.%Y %H:%M:%S")
            case_dt = case_dt.replace(tzinfo=self.tz)

            response_dt = msg_date.astimezone(self.tz)
            effective_start = self.get_effective_start(case_dt)

            response_minutes = self.working_minutes_between(effective_start, response_dt)
            response_minutes = self.subtract_lunch(response_minutes, effective_start, response_dt)

            sla = "OK" if response_minutes <= self.sla_minutes else "Missed"

            ws = sheets.get_worksheet("Cases")

            ws.update_cell(open_case_row, 7, response_dt.strftime("%H:%M:%S"))
            ws.update_cell(open_case_row, 8, response_minutes)
            ws.update_cell(open_case_row, 9, username)
            ws.update_cell(open_case_row, 10, "Closed")
            ws.update_cell(open_case_row, 11, sla)

            logger.success(
                f"Case закрыт | {open_case.get('Case ID')} | "
                f"Ответ: {response_minutes} мин | SLA: {sla} | {username}"
            )

        except Exception as e:
            logger.error(f"Ошибка при закрытии Case: {e}")

    def register(self):
        self.load_references()

        @self.client.on(events.NewMessage)
        async def handler(event):
            await self.handle_new_message(event)

        logger.success("Обработчик сообщений зарегистрирован")