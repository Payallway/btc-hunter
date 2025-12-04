import logging
import os
import json
from datetime import datetime

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

import aiosqlite
from openai import OpenAI

# ================== ЛОГИ ==================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ================== ENV ==================

load_dotenv(".env")

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not BOT_TOKEN:
    raise RuntimeError("❌ BOT_TOKEN не найден в .env")
if not OPENAI_API_KEY:
    raise RuntimeError("❌ OPENAI_API_KEY не найден в .env")

# ================== OPENAI CLIENT ==================

client = OpenAI(api_key=OPENAI_API_KEY)

# ================== DB ==================

DB_PATH = "offers.db"


async def init_db() -> None:
    """Создаём/мигрируем таблицу офферов."""
    async with aiosqlite.connect(DB_PATH) as db:
        # Базовая схема (с уже новыми полями kind, fee_percent)
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS offers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                raw_text TEXT NOT NULL,
                country TEXT,
                method TEXT,
                fee TEXT,
                rate TEXT,
                limits TEXT,
                conditions TEXT,
                status TEXT NOT NULL DEFAULT 'new',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        await db.commit()

        # Проверяем существующие колонки
        cursor = await db.execute("PRAGMA table_info(offers);")
        cols = [row[1] for row in await cursor.fetchall()]

        # kind: channel / merchant
        if "kind" not in cols:
            await db.execute("ALTER TABLE offers ADD COLUMN kind TEXT;")

        # fee_percent: числовое значение комиссии (в процентах)
        if "fee_percent" not in cols:
            await db.execute("ALTER TABLE offers ADD COLUMN fee_percent REAL;")

        await db.commit()

    logger.info("📚 База данных готова (%s)", DB_PATH)


async def save_offer(parsed: dict, raw_text: str) -> int:
    """Сохраняем оффер в БД, возвращаем ID."""
    now = datetime.utcnow().isoformat()

    # Достаём поля из парсинга
    country = parsed.get("country")
    method = parsed.get("method")
    fee = parsed.get("fee")
    rate = parsed.get("rate")
    limits = parsed.get("limits")
    conditions = parsed.get("conditions")
    kind = parsed.get("kind")  # "channel" / "merchant" / None
    fee_percent = parsed.get("fee_percent")

    # Пытаемся привести fee_percent к числу
    try:
        fee_percent = float(fee_percent) if fee_percent is not None else None
    except (TypeError, ValueError):
        fee_percent = None

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            INSERT INTO offers (
                raw_text, country, method, fee, rate, limits,
                conditions, status, created_at, updated_at,
                kind, fee_percent
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                raw_text,
                country,
                method,
                fee,
                rate,
                limits,
                conditions,
                "new",
                now,
                now,
                kind,
                fee_percent,
            ),
        )
        await db.commit()
        offer_id = cursor.lastrowid
    return offer_id


async def list_last_offers(limit: int = 10):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            SELECT id, country, method, fee, rate, status, created_at, kind, fee_percent
            FROM offers
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = await cursor.fetchall()
    return rows


async def get_offer_by_id(offer_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            SELECT id, raw_text, country, method, fee, rate,
                   limits, conditions, status, created_at, updated_at,
                   kind, fee_percent
            FROM offers
            WHERE id = ?
            """,
            (offer_id,),
        )
        row = await cursor.fetchone()
    return row


async def search_offers(filters: dict, limit: int = 20):
    """
    Поиск офферов по фильтрам:
    country, method, status, kind, min_fee_percent, max_fee_percent
    """
    conditions = []
    params = []

    country = filters.get("country")
    method = filters.get("method")
    status = filters.get("status")
    kind = filters.get("kind")
    min_fee = filters.get("min_fee_percent")
    max_fee = filters.get("max_fee_percent")

    if country:
        conditions.append("LOWER(country) LIKE ?")
        params.append(f"%{country.lower()}%")
    if method:
        conditions.append("LOWER(method) LIKE ?")
        params.append(f"%{method.lower()}%")
    if status:
        conditions.append("status = ?")
        params.append(status)
    if kind:
        conditions.append("kind = ?")
        params.append(kind)
    if min_fee is not None:
        conditions.append("fee_percent >= ?")
        params.append(float(min_fee))
    if max_fee is not None:
        conditions.append("fee_percent <= ?")
        params.append(float(max_fee))

    where_clause = " AND ".join(conditions) if conditions else "1=1"

    sql = f"""
        SELECT id, country, method, fee, rate, status, kind, fee_percent
        FROM offers
        WHERE {where_clause}
        ORDER BY id DESC
        LIMIT ?
    """
    params.append(limit)

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(sql, params)
        rows = await cursor.fetchall()
    return rows


# ================== OPENAI ЛОГИКА ==================


async def interpret_text_with_openai(text: str) -> dict:
    """
    Определяем: это ОФФЕР или ПОИСК.
    Возвращаем JSON вида:
    {
      "mode": "offer" | "search",
      "offer": {
        "country": ...,
        "method": ...,
        "fee": ...,
        "rate": ...,
        "limits": ...,
        "conditions": ...,
        "kind": "channel" | "merchant" | null,
        "fee_percent": 10.5 | null,
        "short_summary": "..."
      },
      "search": {
        "country": "india" | null,
        "method": "sbp" | null,
        "status": "new|active|paused|closed|null",
        "kind": "channel|merchant|null",
        "min_fee_percent": 5.0 | null,
        "max_fee_percent": 11.0 | null
      }
    }
    """
    system_prompt = (
        "Ты ассистент CRM агрегатора платежей.\n"
        "Пользователь может:\n"
        "1) прислать ОФФЕР (описание платёжного канала или мерчанта);\n"
        "2) задать ПОИСКОВЫЙ ЗАПРОС по базе офферов простыми словами.\n\n"
        "Твоя задача — определить режим и вернуть ТОЛЬКО валидный JSON.\n"
        "Никакого текста кроме JSON.\n\n"
        "Правила:\n"
        "- Если это описание конкретного канала/мерчанта с условиями — это 'offer'.\n"
        "- Если фразы вида 'дай все офферы...', 'покажи офферы по ...', "
        " 'офферы по сбп рф дешевле 11%' — это 'search'.\n"
        "- 'kind' = 'channel', если это канал/провайдер; 'merchant', если конкретный мерчант.\n"
        "- 'fee_percent' — числовое значение комиссии в процентах (если понятно, иначе null).\n"
        "- В поиске country/method/status/kind — короткие текстовые маркеры для фильтрации.\n"
        "- Проценты в поиске: 'дешевле 11%' => max_fee_percent = 11.0.\n"
    )

    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text},
        ],
    )

    content = resp.choices[0].message.content
    logger.info("OpenAI interpret response: %s", content)

    try:
        data = json.loads(content)
        if not isinstance(data, dict):
            raise ValueError("JSON не является объектом")
        return data
    except Exception as e:
        raise RuntimeError(f"Не удалось распарсить JSON OpenAI: {e}\nОтвет: {content}")


# ================== HANDLERS ==================


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
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


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text or ""
    chat_id = update.effective_chat.id

    await update.message.reply_text("⏳ Думаю над запросом...")

    try:
        data = await interpret_text_with_openai(user_text)
        mode = data.get("mode")

        # ---------- РЕЖИМ ОФФЕРА ----------
        if mode == "offer":
            parsed = (data.get("offer") or {})
            offer_id = await save_offer(parsed, user_text)

            msg_lines = [
                f"✅ Оффер сохранён. ID: *{offer_id}*",
                "",
                f"*Тип:* {parsed.get('kind') or '—'}",  # channel / merchant
                f"*Страна:* {parsed.get('country') or '—'}",
                f"*Метод:* {parsed.get('method') or '—'}",
                f"*Комиссия:* {parsed.get('fee') or '—'}",
                f"*Курс:* {parsed.get('rate') or '—'}",
                f"*Лимиты:* {parsed.get('limits') or '—'}",
                f"*Условия:* {parsed.get('conditions') or '—'}",
            ]

            fee_percent = parsed.get("fee_percent")
            if fee_percent is not None:
                msg_lines.append(f"*Комиссия, %:* {fee_percent}")

            short_summary = parsed.get("short_summary")
            if short_summary:
                msg_lines.extend(["", f"_Краткое резюме:_ {short_summary}"])

            text = "\n".join(msg_lines)

            await context.bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode="Markdown",
            )

        # ---------- РЕЖИМ ПОИСКА ----------
        elif mode == "search":
            filters = data.get("search") or {}
            rows = await search_offers(filters, limit=20)

            if not rows:
                await update.message.reply_text("Ничего не нашёл по этому запросу 🤷‍♂️")
                return

            lines = ["📋 *Результаты поиска:*", ""]
            for row in rows:
                oid, country, method, fee, rate, status, kind, fee_percent = row
                kind_str = kind or "—"
                fee_str = fee or (f"{fee_percent}%" if fee_percent is not None else "—")
                lines.append(
                    f"ID *{oid}* — [{kind_str}] {country or '—'} / {method or '—'} / "
                    f"{fee_str} / {rate or 'курс ?'} — _{status}_"
                )

            await update.message.reply_text(
                "\n".join(lines),
                parse_mode="Markdown",
            )

        # ---------- НЕ ОПРЕДЕЛИЛСЯ ----------
        else:
            await update.message.reply_text(
                "Я не понял, это оффер или поиск 🤔\n"
                "Попробуй переформулировать или начни с чего-то вроде:\n"
                "— 'дай офферы по ...'\n"
                "— или просто пришли оффер."
            )

    except Exception as e:
        logger.exception("Ошибка в обработке текста")
        await update.message.reply_text(
            "❌ Ошибка при обработке:\n"
            f"{e}"
        )


async def cmd_offers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = await list_last_offers(limit=10)
    if not rows:
        await update.message.reply_text("Пока офферов нет. Отправь первый текст оффера.")
        return

    lines = ["📋 *Последние офферы:*", ""]
    for row in rows:
        oid, country, method, fee, rate, status, created_at, kind, fee_percent = row
        kind_str = kind or "—"
        fee_str = fee or (f"{fee_percent}%" if fee_percent is not None else "—")
        lines.append(
            f"ID *{oid}* — [{kind_str}] {country or '—'} / {method or '—'} / "
            f"{fee_str} / {rate or 'курс ?'} — _{status}_"
        )
    text = "\n".join(lines)

    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_offer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Использование: /offer <id>")
        return

    try:
        oid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("ID должен быть числом, пример: /offer 12")
        return

    row = await get_offer_by_id(oid)
    if not row:
        await update.message.reply_text(f"Оффер с ID {oid} не найден.")
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


# ================== MAIN ==================


async def post_init(application):
    await init_db()


def main():
    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("offers", cmd_offers))
    app.add_handler(CommandHandler("offer", cmd_offer))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    logger.info("🚀 Бот запущен с CRM + поиском...")
    app.run_polling()


if __name__ == "__main__":
    main()
