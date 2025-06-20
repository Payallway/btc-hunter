import os
import time
import logging
import threading
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from pytz import timezone
from telegram import Bot
from bip_utils import (
    Bip39SeedGenerator,
    Bip44,
    Bip44Coins,
    Bip44Changes,
    Bip39MnemonicValidator,
)

# Telegram setup
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
    raise EnvironmentError(
        "TELEGRAM_TOKEN and TELEGRAM_CHAT_ID environment variables must be set"
    )

bot = Bot(token=TELEGRAM_TOKEN)

# Logging
logging.basicConfig(filename="log.txt", level=logging.INFO)
logger = logging.getLogger()

# Paths
DICTIONARY_DIR = "."

# Settings
CHECK_INTERVAL = 600  # seconds

# Load words
with open(os.path.join(DICTIONARY_DIR, "brainwallet.txt"), "r", encoding="utf-8") as f:
    brainwallets = [line.strip() for line in f if line.strip()]

with open(os.path.join(DICTIONARY_DIR, "mnemonic.txt"), "r", encoding="utf-8") as f:
    mnemonic_phrases = [line.strip() for line in f if len(line.strip().split()) == 12]

broken_path = os.path.join(DICTIONARY_DIR, "broken_seeds.txt")
if os.path.exists(broken_path):
    with open(broken_path, "r", encoding="utf-8") as f:
        broken_seeds = [line.strip() for line in f if len(line.strip().split()) == 12]
else:
    logging.warning("broken_seeds.txt not found, skipping")
    broken_seeds = []

def mnemonic_to_address(mnemonic_phrase: str) -> str:
    """Convert a BIP39 mnemonic to the first Bitcoin address."""
    seed_bytes = Bip39SeedGenerator(mnemonic_phrase).Generate()
    bip44_mst = Bip44.FromSeed(seed_bytes, Bip44Coins.BITCOIN)
    return (
        bip44_mst
        .Purpose()
        .Coin()
        .Account(0)
        .Change(Bip44Changes.CHAIN_EXT)
        .AddressIndex(0)
        .PublicKey()
        .ToAddress()
    )

def check_and_report(phrase, mode):
    try:
        if len(phrase.strip().split()) != 12:
            return
        if not Bip39MnemonicValidator(phrase).Validate():
            logger.warning(f"[{mode}] invalid mnemonic skipped: '{phrase}'")
            return
        address = mnemonic_to_address(phrase)
        balance = 0  # Here would be a real balance check
        if balance > 0:
            msg = f"💰 Найден адрес с балансом >0!\n{address}\nБаланс: {balance} сатоши"
            bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=msg)
    except Exception as e:
        logger.error(f"[{mode}] ошибка в фразе: '{phrase}' -> {e}")

def process_brain():
    bot.send_message(chat_id=TELEGRAM_CHAT_ID, text="🧵 Стартую режим: brain")
    for phrase in brainwallets:
        check_and_report(phrase, "brain")

def process_mnemonic():
    bot.send_message(chat_id=TELEGRAM_CHAT_ID, text="🧵 Стартую режим: mnemonic")
    for phrase in mnemonic_phrases:
        check_and_report(phrase, "mnemonic")

def process_broken():
    bot.send_message(chat_id=TELEGRAM_CHAT_ID, text="🧵 Стартую режим: broken")
    for phrase in broken_seeds:
        check_and_report(phrase, "broken")

def report():
    now = datetime.now().strftime('%H:%M:%S')
    bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=f"🧑🏽‍💻 Статус: {now}")

if __name__ == "__main__":
    bot.send_message(chat_id=TELEGRAM_CHAT_ID, text="🚀 btc_v36.py стартовал. Запускаю потоки...")

    threading.Thread(target=process_brain).start()
    threading.Thread(target=process_mnemonic).start()
    threading.Thread(target=process_broken).start()

    bot.send_message(chat_id=TELEGRAM_CHAT_ID, text="🚀 Запуск HUNTER ULTIMATE...")

    scheduler = BackgroundScheduler(timezone=timezone("UTC"))
    scheduler.add_job(report, 'interval', seconds=CHECK_INTERVAL)
    scheduler.start()

    while True:
        time.sleep(60)
