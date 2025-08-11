import os
import logging
import asyncio
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# Logging setup
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ✅ Get the token from Railway variable
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Example command: /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Chipomatic is online 🚀\nI'll send you the CHIPS price every few minutes.")

# Example function to fetch price (replace with real API later)
async def get_chip_price():
    # TODO: Replace this with your actual price fetch from dexscreener API
    return "0.042 SOL"

# Command to get price now
async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    price = await get_chip_price()
    await update.message.reply_text(f"💰 Current CHIPS price: {price}")

def main():
    if not TELEGRAM_TOKEN:
        raise ValueError("No TELEGRAM_BOT_TOKEN environment variable found!")

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("price", price))

    logger.info("Bot started...")
    app.run_polling()

if __name__ == "__main__":
    main()
