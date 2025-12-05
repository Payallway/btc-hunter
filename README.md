# BTC Hunter Bot

Новая версия CRM-бота для приёма и поиска офферов в Telegram.

## Запуск
1. Создать файл `.env` с переменными:
   ```env
   BOT_TOKEN=...
   OPENAI_API_KEY=...
   OPENAI_MODEL=gpt-4o-mini
   DB_PATH=offers.db
   LOG_LEVEL=INFO
   ```
2. Установить зависимости (`python-telegram-bot`, `openai`, `aiosqlite`, `python-dotenv`).
3. Запустить бота:
   ```bash
   python bot.py
   ```

## Структура
- `src/config.py` — загрузка конфигурации и настройка логирования.
- `src/database.py` — асинхронный слой работы с SQLite.
- `src/openai_service.py` — интерпретация текстов через OpenAI.
- `src/service.py` — бизнес-логика и обработчики команд/сообщений.
- `src/main.py` — сборка `Application` Telegram и точка входа.
