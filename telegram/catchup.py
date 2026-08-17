from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import asyncio
from loguru import logger
from sheets.client import sheets


class CatchUp:
    def __init__(self, client, handler):
        self.client = client
        self.handler = handler
        self.tz = ZoneInfo("Asia/Tashkent")

    def get_last_case_time(self) -> datetime:
        cases = sheets.get_all_cases()
        if not cases:
            today = datetime.now(self.tz).replace(hour=0, minute=0, second=0, microsecond=0)
            logger.info("Cases пустой — догружаем с начала сегодняшнего дня")
            return today

        last = cases[-1]
        date_str = str(last.get("Дата", "")).strip()
        time_str = str(last.get("Время", "")).strip()

        try:
            dt = datetime.strptime(f"{date_str} {time_str}", "%d.%m.%Y %H:%M:%S")
            return dt.replace(tzinfo=self.tz)
        except Exception:
            today = datetime.now(self.tz).replace(hour=0, minute=0, second=0, microsecond=0)
            return today

    def get_oldest_open_case_time(self) -> datetime | None:
        cases = sheets.get_all_cases()
        oldest = None

        for case in cases:
            if str(case.get("Status", "")).strip() != "Open":
                continue
            date_str = str(case.get("Дата", "")).strip()
            time_str = str(case.get("Время", "")).strip()
            try:
                dt = datetime.strptime(f"{date_str} {time_str}", "%d.%m.%Y %H:%M:%S")
                dt = dt.replace(tzinfo=self.tz)
                if oldest is None or dt < oldest:
                    oldest = dt
            except Exception:
                continue

        return oldest

    def case_already_exists(self, group_name: str, track: str, msg_dt: datetime) -> bool:
        if not track:
            return False

        cases = sheets.get_all_cases()
        date_str = msg_dt.strftime("%d.%m.%Y")
        time_prefix = msg_dt.strftime("%H:%M")

        for case in cases:
            if str(case.get("Group", "")).strip() != group_name:
                continue
            if str(case.get("Track", "")).strip() != track:
                continue
            if str(case.get("Дата", "")).strip() != date_str:
                continue
            if str(case.get("Время", "")).strip().startswith(time_prefix):
                return True
        return False

    async def build_dialogs_map(self):
        dialogs_map = {}
        async for d in self.client.iter_dialogs():
            if d.name:
                dialogs_map[d.name.strip().lower()] = d
        return dialogs_map

    def find_dialog(self, dialogs_map, group_name: str):
        key = group_name.lower()
        dialog = dialogs_map.get(key)
        if dialog:
            return dialog

        for name, d in dialogs_map.items():
            if key in name or name in key:
                return d
        return None

    async def close_open_cases_from_history(self, dialogs_map):
        logger.info("=== Закрытие Open Cases по истории ===")

        cases = sheets.get_all_cases()
        closed_count = 0
        open_list = [
            case for case in cases
            if str(case.get("Status", "")).strip() == "Open"
        ]

        logger.info(f"Открытых Cases: {len(open_list)}")

        for case in open_list:
            group_name = str(case.get("Group", "")).strip()
            case_date = str(case.get("Дата", "")).strip()
            case_time = str(case.get("Время", "")).strip()
            case_id = str(case.get("Case ID", "")).strip()

            if not group_name:
                continue

            try:
                case_dt = datetime.strptime(
                    f"{case_date} {case_time}", "%d.%m.%Y %H:%M:%S"
                ).replace(tzinfo=self.tz)
            except Exception:
                logger.warning(f"Не удалось разобрать дату Case {case_id}")
                continue

            dialog = self.find_dialog(dialogs_map, group_name)
            if not dialog:
                logger.warning(f"Группа не найдена: {group_name}")
                continue

            logger.info(f"Ищем ответ для {case_id} | {group_name}")

            try:
                found = False
                async for msg in self.client.iter_messages(
                    dialog.entity,
                    offset_date=case_dt,
                    reverse=True,
                    limit=50,
                ):
                    msg_dt = msg.date.astimezone(self.tz)
                    if msg_dt <= case_dt:
                        continue

                    if not msg.sender_id:
                        continue

                    sender = await msg.get_sender()
                    if not self.handler.is_employee(sender):
                        continue

                    merchant = str(case.get("Merchant", "")).strip() or group_name
                    await self.handler.process_employee_reply(
                        merchant=merchant,
                        group_name=group_name,
                        text=msg.text or "",
                        msg_date=msg.date,
                        sender=sender,
                    )
                    closed_count += 1
                    found = True
                    await asyncio.sleep(2)
                    break

                if not found:
                    logger.info(f"Ответа сотрудника не найдено: {case_id}")

            except Exception as e:
                logger.error(f"Ошибка закрытия {case_id} в {group_name}: {e}")
                await asyncio.sleep(3)

        logger.success(f"Закрыто Open Cases по истории: {closed_count}")
        return closed_count

    async def find_employee_reply_after(self, dialog, after_dt: datetime):
        try:
            async for msg in self.client.iter_messages(
                dialog.entity,
                offset_date=after_dt,
                reverse=True,
                limit=40,
            ):
                msg_dt = msg.date.astimezone(self.tz)
                if msg_dt <= after_dt:
                    continue

                if not msg.sender_id:
                    continue

                sender = await msg.get_sender()
                if self.handler.is_employee(sender):
                    return msg, sender
        except Exception as e:
            logger.error(f"Ошибка поиска ответа сотрудника: {e}")

        return None, None

    async def load_new_merchant_messages(self, dialogs_map, since: datetime):
        """
        Догрузка Cases с учётом режима группы (normal / mention).
        """
        logger.info("=== Догрузка Cases (с учётом mention) ===")

        groups_data = sheets.get_groups()
        total_cases = 0
        total_closed = 0
        skipped_mention = 0
        processed_groups = 0

        for g in groups_data:
            group_name = str(g.get("Telegram Group", "")).strip()
            merchant = str(g.get("Merchant", "")).strip()

            if not group_name or not merchant:
                continue

            mode = str(g.get("Режим", "") or g.get("Mode", "")).strip().lower()
            if mode not in ("mention", "normal"):
                mode = "normal"

            dialog = self.find_dialog(dialogs_map, group_name)
            if not dialog:
                continue

            processed_groups += 1

            try:
                async for msg in self.client.iter_messages(
                    dialog.entity,
                    offset_date=since,
                    reverse=True,
                    limit=30,
                ):
                    msg_dt = msg.date.astimezone(self.tz)
                    if msg_dt < since:
                        continue

                    if not msg.text:
                        continue

                    sender = await msg.get_sender()
                    if self.handler.is_employee(sender):
                        continue

                    if not self.handler.is_valid_request(msg.text or ""):
                        continue

                    # Режим mention: только с @ MC
                    if mode == "mention":
                        if not self.handler.has_mc_mention(msg.text or ""):
                            skipped_mention += 1
                            continue

                    track = self.handler.extract_track(msg.text or "")
                    phone = self.handler.extract_phone(msg.text or "")
                    track_value = track if track else phone

                    if self.case_already_exists(group_name, track_value, msg_dt):
                        logger.info(f"Пропуск дубликата: {track_value} | {group_name}")
                        continue

                    await self.handler.create_case(
                        merchant=merchant,
                        group_name=group_name,
                        text=msg.text or "",
                        msg_date=msg.date,
                        sender=sender,
                    )
                    total_cases += 1
                    await asyncio.sleep(2)

                    reply_msg, reply_sender = await self.find_employee_reply_after(
                        dialog, msg_dt
                    )
                    if reply_msg and reply_sender:
                        await self.handler.process_employee_reply(
                            merchant=merchant,
                            group_name=group_name,
                            text=reply_msg.text or "",
                            msg_date=reply_msg.date,
                            sender=reply_sender,
                        )
                        total_closed += 1
                        logger.info(
                            f"Case сразу закрыт (ответ уже был) | {track_value}"
                        )
                        await asyncio.sleep(2)

            except Exception as e:
                logger.error(f"Ошибка догрузки {group_name}: {e}")
                await asyncio.sleep(3)

        logger.success(
            f"Догрузка: групп {processed_groups} | "
            f"Cases {total_cases} | Сразу закрыто {total_closed} | "
            f"Пропуск mention без @: {skipped_mention}"
        )
        return total_cases

    async def run(self):
        logger.info("=== Начинаем догрузку истории ===")

        last_time = self.get_last_case_time()
        oldest_open = self.get_oldest_open_case_time()

        since = last_time - timedelta(minutes=2)
        if oldest_open and oldest_open < since:
            since = oldest_open - timedelta(minutes=1)
            logger.info(
                f"Есть Open Cases с {oldest_open.strftime('%d.%m.%Y %H:%M')} — расширяем догрузку"
            )

        min_since = datetime.now(self.tz) - timedelta(days=1)
        if since < min_since:
            since = min_since

        logger.info(f"Догрузка с: {since.strftime('%d.%m.%Y %H:%M:%S')}")
        logger.info(f"Последний Case: {last_time.strftime('%d.%m.%Y %H:%M:%S')}")

        logger.info("Загружаем список диалогов...")
        dialogs_map = await self.build_dialogs_map()
        logger.info(f"Загружено диалогов: {len(dialogs_map)}")

        logger.info("Пропуск закрытия старых Open (экономия квоты)")
        # await self.close_open_cases_from_history(dialogs_map)

        await self.load_new_merchant_messages(dialogs_map, since)

        logger.success("Догрузка полностью завершена")