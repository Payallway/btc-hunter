import logging
import subprocess
from datetime import datetime
from typing import Any, Dict, List

from telegram import Update
from telegram.ext import ContextTypes

from .database import OfferRepository
from .openai_service import OfferInterpreter

logger = logging.getLogger(__name__)


def get_last_commit_hash() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"]).decode().strip()
    except Exception as exc:  # noqa: BLE001
        logger.error("Не удалось получить хеш коммита: %s", exc)
        return "unknown"


class BotService:
    def __init__(self, offers: OfferRepository, interpreter: OfferInterpreter) -> None:
        self.offers = offers
        self.interpreter = interpreter
        self.started_at = datetime.utcnow().isoformat() + "Z"
        self.commit_hash = get_last_commit_hash()

    async def handle_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.message.reply_text(
            "👋 Привет! Я CRM-бот агрегатора.\n\n"
            "Я умею:\n"
            "1) Принимать офферы (каналы/мерчи) и сохранять их в базу.\n"
            "2) Искать по базе простыми фразами.\n\n"
            "Примеры:\n"
            "- RU SBP вход 1.8% курс 98 лимиты 10k–300k\n"
            "- дай все офферы по индии\n"
            "- дай офферы по сбп рф дешевле 11%\n\n"
            "Последние офферы: /offers\n"
            "Оффер по ID: /offer 10"
        )

    async def handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_text = update.message.text or ""
        chat_id = update.effective_chat.id

        await update.message.reply_text("⏳ Думаю над запросом...")

        try:
            data = await self.interpreter.interpret(user_text)
            mode = data.get("mode")

            if mode == "offer":
                await self._handle_offer_mode(data, user_text, chat_id, context)
            elif mode == "search":
                await self._handle_search_mode(data, update)
            else:
                await update.message.reply_text(
                    "Я не понял, это оффер или поиск 🤔\n"
                    "Попробуй переформулировать или начни с чего-то вроде:\n"
                    "— 'дай офферы по ...'\n"
                    "— или просто пришли оффер."
                )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Ошибка в обработке текста")
            await update.message.reply_text(
                "❌ Ошибка при обработке:\n"
                f"{exc}"
            )

    async def handle_offers(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        rows = await self.offers.list_last_offers(limit=10)
        if not rows:
            await update.message.reply_text("Пока офферов нет. Отправь первый текст оффера.")
            return

        lines: List[str] = ["📋 *Последние офферы:*", ""]
        for row in rows:
            oid, country, method, fee, rate, status, created_at, kind, fee_percent = row
            kind_str = kind or "—"
            fee_str = fee or (f"{fee_percent}%" if fee_percent is not None else "—")
            lines.append(
                f"ID *{oid}* — [{kind_str}] {country or '—'} / {method or '—'} / "
                f"{fee_str} / {rate or 'курс ?'} — _{status}_"
            )
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    async def handle_offer(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not context.args:
            await update.message.reply_text("Использование: /offer <id>")
            return

        try:
            offer_id = int(context.args[0])
        except ValueError:
            await update.message.reply_text("ID должен быть числом, пример: /offer 12")
            return

        row = await self.offers.get_offer_by_id(offer_id)
        if not row:
            await update.message.reply_text(f"Оффер с ID {offer_id} не найден.")
            return

        (
            oid,
            raw_text,
            country,
            method,
            fee,
            rate,
            limits,
            conditions,
            status,
            created_at,
            updated_at,
            kind,
            fee_percent,
        ) = row

        kind_str = kind or "—"
        fee_str = fee or (f"{fee_percent}%" if fee_percent is not None else "—")

        lines = [
            f"📄 *Оффер ID {oid}*",
            f"Тип: _{kind_str}_",
            f"Статус: _{status}_",
            "",
            f"*Страна:* {country or '—'}",
            f"*Метод:* {method or '—'}",
            f"*Комиссия:* {fee_str}",
            f"*Курс:* {rate or '—'}",
            f"*Лимиты:* {limits or '—'}",
            f"*Условия:* {conditions or '—'}",
            "",
            f"*Создан:* {created_at}",
            f"*Обновлён:* {updated_at}",
            "",
            "*Исходный текст:*",
            raw_text,
        ]

        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    async def handle_version(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        lines = [
            "ℹ️ *Версия бота*",
            f"Commit: `{self.commit_hash}`",
            f"Запущен: {self.started_at}",
        ]
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    async def _handle_offer_mode(
        self, data: Dict[str, Any], user_text: str, chat_id: int, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        parsed = data.get("offer") or {}
        offer_id = await self.offers.save_offer(parsed, user_text)

        lines: List[str] = [
            f"✅ Оффер сохранён. ID: *{offer_id}*",
            "",
            f"*Тип:* {parsed.get('kind') or '—'}",
            f"*Страна:* {parsed.get('country') or '—'}",
            f"*Метод:* {parsed.get('method') or '—'}",
            f"*Комиссия:* {parsed.get('fee') or '—'}",
            f"*Курс:* {parsed.get('rate') or '—'}",
            f"*Лимиты:* {parsed.get('limits') or '—'}",
            f"*Условия:* {parsed.get('conditions') or '—'}",
        ]

        fee_percent = parsed.get("fee_percent")
        if fee_percent is not None:
            lines.append(f"*Комиссия, %:* {fee_percent}")

        short_summary = parsed.get("short_summary")
        if short_summary:
            lines.extend(["", f"_Краткое резюме:_ {short_summary}"])

        await context.bot.send_message(chat_id=chat_id, text="\n".join(lines), parse_mode="Markdown")

    async def _handle_search_mode(self, data: Dict[str, Any], update: Update) -> None:
        filters = data.get("search") or {}
        rows = await self.offers.search_offers(filters, limit=20)

        if not rows:
            await update.message.reply_text("Ничего не нашёл по этому запросу 🤷‍♂️")
            return

        lines: List[str] = ["📋 *Результаты поиска:*", ""]
        for row in rows:
            oid, country, method, fee, rate, status, kind, fee_percent = row
            kind_str = kind or "—"
            fee_str = fee or (f"{fee_percent}%" if fee_percent is not None else "—")
            lines.append(
                f"ID *{oid}* — [{kind_str}] {country or '—'} / {method or '—'} / "
                f"{fee_str} / {rate or 'курс ?'} — _{status}_"
            )

        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
