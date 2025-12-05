import logging
import os
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv


@dataclass
class Settings:
    bot_token: str
    openai_api_key: str
    openai_model: str = "gpt-4.1"
    db_path: str = "offers.db"
    log_level: str = "INFO"


class SettingsFactory:
    """Loads configuration from environment variables with defaults."""

    @staticmethod
    def load_from_env(dotenv_path: str = ".env") -> Settings:
        load_dotenv(dotenv_path)

        bot_token = os.getenv("BOT_TOKEN")
        openai_api_key = os.getenv("OPENAI_API_KEY")
        openai_model = os.getenv("OPENAI_MODEL", Settings.openai_model)
        db_path = os.getenv("DB_PATH", Settings.db_path)
        log_level = os.getenv("LOG_LEVEL", Settings.log_level)

        missing = [name for name, value in {"BOT_TOKEN": bot_token, "OPENAI_API_KEY": openai_api_key}.items() if not value]
        if missing:
            raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")

        return Settings(
            bot_token=bot_token,
            openai_api_key=openai_api_key,
            openai_model=openai_model,
            db_path=db_path,
            log_level=log_level,
        )


def configure_logging(level: Optional[str] = None) -> None:
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=getattr(logging, (level or "INFO").upper(), logging.INFO),
    )
