import logging
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters

from .config import SettingsFactory, configure_logging
from .database import OfferRepository
from .openai_service import OfferInterpreter
from .service import BotService


def build_application():
    settings = SettingsFactory.load_from_env()
    configure_logging(settings.log_level)
    logging.getLogger(__name__).info(
        "⚙️ Конфигурация: DB_PATH=%s, OPENAI_MODEL=%s", settings.db_path, settings.openai_model
    )

    offers_repo = OfferRepository(settings.db_path)
    interpreter = OfferInterpreter(settings.openai_api_key, settings.openai_model)
    bot_service = BotService(offers_repo, interpreter)

    async def post_init(application):
        await offers_repo.init()

    application = (
        ApplicationBuilder()
        .token(settings.bot_token)
        .post_init(post_init)
        .build()
    )

    application.add_handler(CommandHandler("start", bot_service.handle_start))
    application.add_handler(CommandHandler("version", bot_service.handle_version))
    application.add_handler(CommandHandler("offers", bot_service.handle_offers))
    application.add_handler(CommandHandler("offer", bot_service.handle_offer))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot_service.handle_text))

    return application


def main():
    application = build_application()
    application.run_polling()


if __name__ == "__main__":
    main()
