import re
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from telethon import events
from telethon.tl.types import User
from loguru import logger

from sheets.client import sheets


MC_USERNAMES = [
    "fargo_rail",
    "merchant_care_fargo",
    "fargo_merchant_care_ibrohim",
    "fargo_merchant_care_sarvar",
]


class MessageHandler:
    def __init__(self, client):
        self.client = client
        self.tz = ZoneInfo("Asia/Tashkent")
        self.employees = {}
        self.groups = {}
        self.sla_minutes = 20
        self.duty_name = None

    def load_references(self):
        employees_raw = sheets.get_employees()
        self.employees = {}
        for row in employees_raw:
            raw = str(row.get("Telegram", "") or row.get("Username", "")).strip()
            if not raw:
                continue
            uname = raw.lstrip("@").strip()
            if not uname:
                continue
            name = str(
                row.get("Сотрудник", "") or row.get("Employee", "") or uname
            ).strip()
            self.employees[uname.lower()] = {
                "name": name,
                "username_original": uname,
            }
        logger.info(f"Загружено сотрудников: {len(self.employees)}")

        groups_raw = sheets.get_groups()
        self.groups = {}
        for row in groups_raw:
            title = str(row.get("Telegram Group", "")).strip()
            merchant = str(row.get("Merchant", "")).strip()
            if not title or not merchant:
                continue
            responsible = str(
                row.get("Ответственный", "") or row.get("Responsible", "")
            ).strip()
            mode = str(row.get("Режим", "") or row.get("Mode", "")).strip().lower()
            if mode not in ("mention", "normal"):
                mode = "normal"
            self.groups[title.lower()] = {
                "title": title,
                "merchant": merchant,
                "responsible": responsible,
                "mode": mode,
            }
        logger.info(f"Загружено групп: {len(self.groups)}")
        self.duty_name = self._load_duty()

    def _load_duty(self):
        try:
            rows = sheets.get_employees()
            for row in rows:
                flag = str(
                    row.get("На смене", "") or row.get("Duty", "")
                ).strip().lower()
                if flag in ("да", "yes", "1", "true", "+"):
                    name = str(
                        row.get("Сотрудник", "") or row.get("Employee", "")
                    ).strip()
                    uname = str(
                        row.get("Telegram", "") or row.get("Username", "")
                    ).strip()
                    value = uname if uname else name
                    if value:
                        logger.info(f"На смене: {value}")
                        return value
        except Exception:
            pass
        return None

    def find_group(self, chat_title: str):
        if not chat_title:
            return None
        key = chat_title.strip().lower()
        if key in self.groups:
            return self.groups[key]
        for gkey, info in self.groups.items():
            if gkey in key or key in gkey:
                return info
        return None

    def is_employee(self, sender) -> bool:
        if not sender or not getattr(sender, "username", None):
            return False
        return sender.username.lower() in self.employees

    def get_employee_display(self, sender) -> str:
        if not sender or not getattr(sender, "username", None):
            return "Unknown"
        key = sender.username.lower()
        info = self.employees.get(key)
        if not info:
            return f"@{sender.username}"
        return f"@{info['username_original']}"

    def normalize_employee(self, value: str) -> str:
        if not value:
            return value
        v = str(value).strip()
        key = v.lstrip("@").lower()
        if key in self.employees:
            orig = self.employees[key]["username_original"]
            return f"@{orig.lstrip('@')}"
        for uname, info in self.employees.items():
            name = str(info.get("name", "")).strip().lower()
            if name and name == v.lower():
                orig = info["username_original"]
                return f"@{orig.lstrip('@')}"
        if not v.startswith("@"):
            return v
        return v

    def has_mc_mention(self, text: str) -> bool:
        if not text:
            return False
        lower = text.lower()
        for u in MC_USERNAMES:
            if f"@{u}" in lower:
                return True
        return False

    def resolve_employee_name(self, sender, group_info: dict | None) -> str:
        """Closed_By: личный аккаунт или «На смене» при общем Merchant Care."""
        uname = (sender.username or "").lower() if sender else ""

        if uname and uname != "merchant_care_fargo":
            info = self.employees.get(uname)
            if info:
                return self.normalize_employee(info["username_original"])

        if uname == "merchant_care_fargo":
            if self.duty_name:
                return self.normalize_employee(self.duty_name)
            if group_info and group_info.get("responsible"):
                return self.normalize_employee(group_info["responsible"])
            return "@Merchant_Care_Fargo"

        if group_info and group_info.get("responsible"):
            return self.normalize_employee(group_info["responsible"])

        return self.normalize_employee(self.get_employee_display(sender))

    def resolve_sla_owner(self, closed_by: str, sla: str, group_info: dict | None) -> str:
        """
        OK     → кто закрыл (Closed_By)
        Missed → кто «На смене»; иначе Responsible группы; иначе Closed_By
        """
        if sla == "OK":
            return closed_by

        if self.duty_name:
            return self.normalize_employee(self.duty_name)

        if group_info and group_info.get("responsible"):
            return self.normalize_employee(group_info["responsible"])

        return closed_by

    def extract_track(self, text: str) -> str:
        if not text:
            return ""
        match = re.search(
            r"(TR\d{5,}|TEZ\d{5,}|[A-Z]{2,5}\d{6,}|\b\d{6,20}\b)",
            text.upper(),
        )
        return match.group(0) if match else ""

    def extract_phone(self, text: str) -> str:
        if not text:
            return ""
        match = re.search(
            r"(\+?998\s?\d{2}\s?\d{3}\s?\d{2}\s?\d{2}|\+?\d{9,12})",
            text.replace(" ", ""),
        )
        return match.group(0) if match else ""

    def is_valid_request(self, text: str) -> bool:
        return bool(self.extract_track(text) or self.extract_phone(text))

    def normalize_track(self, value: str) -> str:
        if not value:
            return ""
        return re.sub(r"[^A-Z0-9]", "", str(value).upper())

    def is_working_day(self, dt: datetime) -> bool:
        return dt.weekday() <= 5

    def work_start_end(self, dt: datetime):
        if dt.weekday() == 5:
            return time(10, 0), time(18, 0)
        return time(10, 0), time(19, 0)

    def get_lunch(self):
        try:
            return sheets.get_lunch()
        except Exception:
            return "", ""

    def parse_lunch_datetime(self, value: str):
        value = (value or "").strip()
        if not value:
            return None
        for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%H:%M:%S", "%H:%M"):
            try:
                return datetime.strptime(value, fmt)
            except Exception:
                continue
        return None

    def get_lunch_times_for_day(self, day: datetime):
        lunch_s, lunch_e = self.get_lunch()
        if not lunch_s or not lunch_e:
            return None, None
        ds = self.parse_lunch_datetime(lunch_s)
        de = self.parse_lunch_datetime(lunch_e)
        if not ds or not de:
            return None, None
        lunch_start = day.replace(
            hour=ds.hour, minute=ds.minute,
            second=getattr(ds, "second", 0) or 0, microsecond=0,
        )
        lunch_end = day.replace(
            hour=de.hour, minute=de.minute,
            second=getattr(de, "second", 0) or 0, microsecond=0,
        )
        if lunch_end <= lunch_start:
            return None, None
        return lunch_start, lunch_end

    def get_effective_start(self, case_dt: datetime) -> datetime:
        case_dt = case_dt.astimezone(self.tz)
        start_t, end_t = self.work_start_end(case_dt)
        start_dt = case_dt.replace(
            hour=start_t.hour, minute=start_t.minute, second=0, microsecond=0
        )
        end_dt = case_dt.replace(
            hour=end_t.hour, minute=end_t.minute, second=0, microsecond=0
        )

        if not self.is_working_day(case_dt):
            d = case_dt
            while True:
                d += timedelta(days=1)
                if self.is_working_day(d):
                    st, _ = self.work_start_end(d)
                    return d.replace(hour=st.hour, minute=st.minute, second=0, microsecond=0)

        if case_dt < start_dt:
            return start_dt
        if case_dt >= end_dt:
            d = case_dt
            while True:
                d += timedelta(days=1)
                if self.is_working_day(d):
                    st, _ = self.work_start_end(d)
                    return d.replace(hour=st.hour, minute=st.minute, second=0, microsecond=0)

        lunch_start, lunch_end = self.get_lunch_times_for_day(case_dt)
        if lunch_start and lunch_end and lunch_start <= case_dt < lunch_end:
            return lunch_end
        return case_dt

    def working_minutes_between(self, start: datetime, end: datetime) -> int:
        start = start.astimezone(self.tz)
        end = end.astimezone(self.tz)
        if end <= start:
            return 0
        total = 0.0
        cur = start
        while cur.date() <= end.date():
            if self.is_working_day(cur):
                ws, we = self.work_start_end(cur)
                day_start = cur.replace(hour=ws.hour, minute=ws.minute, second=0, microsecond=0)
                day_end = cur.replace(hour=we.hour, minute=we.minute, second=0, microsecond=0)
                seg_start = max(start, day_start)
                seg_end = min(end, day_end)
                if seg_end > seg_start:
                    mins = (seg_end - seg_start).total_seconds() / 60.0
                    lunch_start, lunch_end = self.get_lunch_times_for_day(cur)
                    if lunch_start and lunch_end:
                        overlap_start = max(seg_start, lunch_start)
                        overlap_end = min(seg_end, lunch_end)
                        if overlap_end > overlap_start:
                            mins -= (overlap_end - overlap_start).total_seconds() / 60.0
                    total += max(0.0, mins)
            cur = (cur + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        return int(round(total))

    async def log_merchant_message(self, merchant: str, group_name: str, msg_date: datetime):
        try:
            dt = msg_date.astimezone(self.tz)
            sheets.append_message([
                dt.strftime("%d.%m.%Y"),
                dt.strftime("%H:%M:%S"),
                merchant,
                group_name,
            ])
        except Exception as e:
            logger.error(f"Ошибка записи Messages: {e}")

    async def create_case(
        self, merchant: str, group_name: str, text: str, msg_date: datetime, sender=None
    ):
        dt = msg_date.astimezone(self.tz)
        track = self.extract_track(text) or self.extract_phone(text) or ""
        case_id = f"C-{dt.strftime('%Y%m%d%H%M%S')}"
        group_info = self.find_group(group_name)
        responsible = ""
        if group_info and group_info.get("responsible"):
            responsible = self.normalize_employee(group_info["responsible"])

        # A–L как раньше + M Responsible + N SLA_Owner (пусто до закрытия)
        row = [
            case_id,
            dt.strftime("%d.%m.%Y"),
            dt.strftime("%H:%M:%S"),
            merchant,
            group_name,
            track,
            "",  # First Response
            "",  # Response Time
            "",  # Employee (Closed_By)
            "Open",
            "",  # SLA
            "",  # Reopened
            responsible,  # Responsible
            "",  # SLA_Owner
        ]
        try:
            sheets.append_case(row)
            logger.success(
                f"Создан Case {case_id} | {merchant} | {group_name} | "
                f"Track: {track} | Responsible: {responsible or '—'}"
            )
        except Exception as e:
            logger.error(f"Ошибка создания Case: {e}")

    async def process_employee_reply(
        self,
        merchant: str,
        group_name: str,
        text: str,
        msg_date: datetime,
        sender,
        reply_msg=None,
    ):
        try:
            if reply_msg is None:
                logger.info(f"Нет reply — Case не закрываем | {group_name}")
                return

            parent_text = reply_msg.message or ""
            parent_track = (
                self.extract_track(parent_text)
                or self.extract_phone(parent_text)
                or ""
            )
            parent_key = self.normalize_track(parent_track)
            if not parent_key:
                logger.info(
                    f"Reply не на сообщение с треком/тел — Case не закрываем | {group_name}"
                )
                return

            cases = sheets.get_all_cases()
            group_info = self.find_group(group_name)
            closed_by = self.resolve_employee_name(sender, group_info)
            reply_dt = msg_date.astimezone(self.tz)

            open_indices = []
            for i, case in enumerate(cases):
                if str(case.get("Status", "")).strip() != "Open":
                    continue
                if str(case.get("Group", "")).strip() != group_name:
                    continue
                case_track = self.normalize_track(str(case.get("Track", "")).strip())
                if case_track and case_track == parent_key:
                    open_indices.append(i)

            if not open_indices:
                logger.info(
                    f"Нет Open Case с Track={parent_track} в {group_name} | {closed_by}"
                )
                return

            ws = sheets.get_worksheet("Cases")
            for i in open_indices:
                case = cases[i]
                case_id = str(case.get("Case ID", ""))
                date_str = str(case.get("Дата", "")).strip()
                time_str = str(case.get("Время", "")).strip()
                try:
                    case_dt = datetime.strptime(
                        f"{date_str} {time_str}", "%d.%m.%Y %H:%M:%S"
                    ).replace(tzinfo=self.tz)
                except Exception:
                    continue

                effective = self.get_effective_start(case_dt)
                response_min = self.working_minutes_between(effective, reply_dt)
                sla = "OK" if response_min <= self.sla_minutes else "Missed"
                sla_owner = self.resolve_sla_owner(closed_by, sla, group_info)

                responsible = str(case.get("Responsible", "")).strip()
                if not responsible and group_info and group_info.get("responsible"):
                    responsible = self.normalize_employee(group_info["responsible"])

                row_num = i + 2
                # G First Response, H Response Time, I Employee, J Status, K SLA,
                # L Reopened (не трогаем), M Responsible, N SLA_Owner
                ws.update(
                    f"G{row_num}:K{row_num}",
                    [[
                        reply_dt.strftime("%d.%m.%Y %H:%M:%S"),
                        response_min,
                        closed_by,
                        "Closed",
                        sla,
                    ]],
                    value_input_option="USER_ENTERED",
                )
                ws.update(
                    f"M{row_num}:N{row_num}",
                    [[responsible, sla_owner]],
                    value_input_option="USER_ENTERED",
                )
                logger.success(
                    f"Case закрыт (reply) | {case_id} | Track: {parent_track} | "
                    f"{response_min} мин | SLA: {sla} | "
                    f"Closed_By: {closed_by} | SLA_Owner: {sla_owner}"
                )
        except Exception as e:
            logger.error(f"Ошибка process_employee_reply: {e}")

    async def handle_new_message(self, event):
        try:
            chat = await event.get_chat()
            if isinstance(chat, User):
                return
            chat_title = getattr(chat, "title", None) or ""
            if not chat_title:
                return

            group_info = self.find_group(chat_title)
            if not group_info:
                return

            merchant = group_info["merchant"]
            group_name = group_info["title"]
            mode = group_info.get("mode", "normal")

            sender = await event.get_sender()
            text = event.message.message or ""
            msg_date = event.message.date

            if self.is_employee(sender):
                logger.info(f"Сотрудник | {group_name} | {(text or '')[:40]}...")
                if not event.message.is_reply:
                    logger.info(f"Не reply — Case не закрываем | {group_name}")
                    return
                reply_msg = await event.get_reply_message()
                if not reply_msg:
                    logger.info(f"Не удалось получить reply | {group_name}")
                    return
                await self.process_employee_reply(
                    merchant, group_name, text, msg_date, sender, reply_msg=reply_msg
                )
                return

            await self.log_merchant_message(merchant, group_name, msg_date)
            logger.info(
                f"Мерчант/коллега | {group_name} | mode={mode} | {(text or '')[:50]}..."
            )

            if not self.is_valid_request(text):
                logger.info("Пропущено (нет трека/телефона)")
                return

            if mode == "mention" and not self.has_mc_mention(text):
                logger.info("Пропущено (режим mention — нет @ MC)")
                return

            await self.create_case(merchant, group_name, text, msg_date, sender)

        except Exception as e:
            logger.error(f"Ошибка обработки сообщения: {e}")

    def register(self):
        self.load_references()

        @self.client.on(events.NewMessage)
        async def _on_message(event):
            await self.handle_new_message(event)

        logger.success("Обработчик сообщений зарегистрирован")