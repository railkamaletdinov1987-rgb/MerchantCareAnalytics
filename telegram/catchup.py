from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
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
        """Время самого старого открытого Case"""
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
        """
        Для каждого Open Case ищем в истории первый ответ сотрудника
        и закрываем Case (в т.ч. ответы с @Merchant_Care_Fargo).
        """
        logger.info("=== Закрытие вчерашних Open Cases по истории ===")

        cases = sheets.get_all_cases()
        closed_count = 0

        for i, case in enumerate(cases):
            if str(case.get("Status", "")).strip() != "Open":
                continue

            group_name = str(case.get("Group", "")).strip()
            case_date = str(case.get("Дата", "")).strip()
            case_time = str(case.get("Время", "")).strip()

            if not group_name:
                continue

            try:
                case_dt = datetime.strptime(
                    f"{case_date} {case_time}", "%d.%m.%Y %H:%M:%S"
                ).replace(tzinfo=self.tz)
            except Exception:
                continue

            dialog = self.find_dialog(dialogs_map, group_name)
            if not dialog:
                logger.warning(f"Группа не найдена для Open Case: {group_name}")
                continue

            try:
                # Ищем первый ответ сотрудника после создания Case
                async for msg in self.client.iter_messages(dialog.entity, reverse=True):
                    msg_dt = msg.date.astimezone(self.tz)

                    if msg_dt < case_dt:
                        continue

                    if not msg.sender_id:
                        continue

                    sender = await msg.get_sender()
                    if not self.handler.is_employee(sender):
                        continue

                    # Нашли ответ сотрудника → закрываем через общую логику
                    merchant = str(case.get("Merchant", "")).strip() or group_name
                    await self.handler.process_employee_reply(
                        merchant=merchant,
                        group_name=group_name,
                        text=msg.text or "",
                        msg_date=msg.date,
                        sender=sender,
                    )
                    closed_count += 1
                    break  # только первый ответ

            except Exception as e:
                logger.error(f"Ошибка закрытия Case в {group_name}: {e}")

        logger.success(f"Закрыто Open Cases по истории: {closed_count}")
        return closed_count

    async def load_new_merchant_messages(self, dialogs_map, since: datetime):
        """Догрузка новых сообщений мерчантов → Messages + Cases"""
        logger.info("=== Догрузка сообщений мерчантов ===")

        groups_data = sheets.get_groups()
        total_cases = 0
        total_messages = 0
        processed_groups = 0

        for g in groups_data:
            group_name = str(g.get("Telegram Group", "")).strip()
            merchant = str(g.get("Merchant", "")).strip()

            if not group_name or not merchant:
                continue

            dialog = self.find_dialog(dialogs_map, group_name)
            if not dialog:
                continue

            processed_groups += 1

            try:
                async for msg in self.client.iter_messages(
                    dialog.entity,
                    offset_date=since,
                    reverse=True,
                ):
                    msg_dt = msg.date.astimezone(self.tz)
                    if msg_dt < since:
                        continue

                    if not msg.text:
                        continue

                    sender = await msg.get_sender()
                    if self.handler.is_employee(sender):
                        continue

                    # Нагрузка — все сообщения мерчантов
                    await self.handler.log_merchant_message(merchant, group_name, msg.date)
                    total_messages += 1

                    # Case — только с треком/телефоном
                    if not self.handler.is_valid_request(msg.text or ""):
                        continue

                    await self.handler.create_case(
                        merchant=merchant,
                        group_name=group_name,
                        text=msg.text or "",
                        msg_date=msg.date,
                        sender=sender,
                    )
                    total_cases += 1

            except Exception as e:
                logger.error(f"Ошибка догрузки {group_name}: {e}")

        logger.success(
            f"Догрузка мерчантов: групп {processed_groups} | "
            f"Messages {total_messages} | Cases {total_cases}"
        )
        return total_cases

    async def run(self):
        logger.info("=== Начинаем догрузку истории ===")

        last_time = self.get_last_case_time()
        oldest_open = self.get_oldest_open_case_time()

        # Берём запас: с самого старого Open Case или с последнего Case
        since = last_time - timedelta(minutes=2)
        if oldest_open and oldest_open < since:
            since = oldest_open - timedelta(minutes=1)
            logger.info(f"Есть Open Cases с {oldest_open.strftime('%d.%m.%Y %H:%M')} — расширяем догрузку")

        # Не глубже 3 суток (защита от очень долгой загрузки)
        min_since = datetime.now(self.tz) - timedelta(days=3)
        if since < min_since:
            since = min_since

        logger.info(f"Догрузка с: {since.strftime('%d.%m.%Y %H:%M:%S')}")
        logger.info(f"Последний Case: {last_time.strftime('%d.%m.%Y %H:%M:%S')}")

        logger.info("Загружаем список диалогов...")
        dialogs_map = await self.build_dialogs_map()
        logger.info(f"Загружено диалогов: {len(dialogs_map)}")

        # 1. Сначала закрываем старые Open по ответам сотрудников
        await self.close_open_cases_from_history(dialogs_map)

        # 2. Потом догружаем новые сообщения мерчантов
        await self.load_new_merchant_messages(dialogs_map, since)

        logger.success("Догрузка полностью завершена")