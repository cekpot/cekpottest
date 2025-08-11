import os
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Read token from env, or fall back to a hardcoded token (TEMPORARY)
TELEGRAM_TOKEN = (os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN") or "").strip()
if not TELEGRAM_TOKEN:
    TELEGRAM_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN_HERE"  # <-- TEMP: replace with your BotFather token

if not TELEGRAM_TOKEN:
    logger.error("Missing/empty TELEGRAM_BOT_TOKEN. Add it to Railway → Variables or hardcode temporarily.")
    exit(1)

# Example bot logic (replace with your own)
from telegram.ext import Updater, CommandHandler

def start(update, context):
    update.message.reply_text("Hello! Your bot is running.")

def main():
    updater = Updater(token=TELEGRAM_TOKEN, use_context=True)
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", start))

    updater.start_polling()
    logger.info("Bot started successfully.")
    updater.idle()

if __name__ == "__main__":
    main()
