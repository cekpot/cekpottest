import os
import re
import aiohttp
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes
)

# --- CONFIG ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAIN = "solana"
PAIR = "fu7dc7yqaepb8qrs9q4tkukss1snejrvxknridtf39bf"  # CHIPS/SOL pair
DEFAULT_INTERVAL = 120  # seconds

JOB_NAME = "price_job"

# --- HELPERS ---
def parse_interval(text: str):
    m = re.fullmatch(r"\s*(\d+)\s*([smhSMH])\s*", text)
    if not m:
        return None
    qty, unit = int(m.group(1)), m.group(2).lower()
    if unit == "s":
        return qty
    if unit == "m":
        return qty * 60
    if unit == "h":
        return qty * 3600
    return None

async def fetch_price():
    url = f"https://api.dexscreener.com/latest/dex/pairs/{CHAIN}/{PAIR}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=10) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
            if "pairs" not in data or not data["pairs"]:
                return None
            p = data["pairs"][0]
            return {
                "price_usd": p.get("priceUsd"),
                "price_sol": p.get("priceNative"),
                "fdv": p.get("fdv"),
                "liq": (p.get("liquidity") or {}).get("usd"),
                "url": p.get("url")
            }

async def send_price(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.chat_id
    info = await fetch_price()
    if not info:
        await context.bot.send_message(chat_id, "Could not fetch CHIPS price.")
        return

    msg = (
        f"CHIPS/SOL price: ${info['price_usd']} ({info['price_sol']} SOL)\n"
        f"FDV: ${int(info['fdv']):,} | Liquidity: ${int(info['liq']):,}\n"
        f"{info['url']}\n"
        "—\n"
        "Powered by Chipomatic"
    )
    await context.bot.send_message(chat_id, msg)

# --- COMMANDS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    # remove old jobs
    for job in context.job_queue.get_jobs_by_name(JOB_NAME + str(chat_id)):
        job.schedule_removal()
    # schedule new job
    context.job_queue.run_repeating(
        send_price, interval=DEFAULT_INTERVAL, first=0,
        chat_id=chat_id, name=JOB_NAME + str(chat_id)
    )
    await update.message.reply_text(
        f"Chipomatic started! Sending CHIPS price every {DEFAULT_INTERVAL//60} minutes.\n"
        "Use /setinterval to change frequency."
    )

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    for job in context.job_queue.get_jobs_by_name(JOB_NAME + str(chat_id)):
        job.schedule_removal()
    await update.message.reply_text("Chipomatic stopped.")

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    info = await fetch_price()
    if not info:
        await update.message.reply_text("Could not fetch CHIPS price.")
        return
    msg = (
        f"CHIPS/SOL price: ${info['price_usd']} ({info['price_sol']} SOL)\n"
        f"FDV: ${int(info['fdv']):,} | Liquidity: ${int(info['liq']):,}\n"
        f"{info['url']}\n"
        "—\n"
        "Powered by Chipomatic"
    )
    await update.message.reply_text(msg)

async def setinterval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /setinterval 30s | 2m | 1h")
        return
    sec = parse_interval(context.args[0])
    if not sec or sec < 10:
        await update.message.reply_text("Minimum interval is 10 seconds.")
        return
    chat_id = update.effective_chat.id
    for job in context.job_queue.get_jobs_by_name(JOB_NAME + str(chat_id)):
        job.schedule_removal()
    context.job_queue.run_repeating(
        send_price, interval=sec, first=0,
        chat_id=chat_id, name=JOB_NAME + str(chat_id)
    )
    await update.message.reply_text(f"Interval updated to {sec} seconds.")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    jobs = context.job_queue.get_jobs_by_name(JOB_NAME + str(chat_id))
    running = bool(jobs)
    interval = jobs[0].interval if running else None
    await update.message.reply_text(
        f"Running: {running}\nInterval: {interval} sec" if running else "Not running."
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "Chipomatic Commands:\n"
        "/start - Start price updates\n"
        "/stop - Stop price updates\n"
        "/price - Get price now\n"
        "/setinterval <time> - Change update frequency (30s, 2m, 1h)\n"
        "/status - Show current settings\n"
        "/help - Show this message"
    )
    await update.message.reply_text(msg)

# --- MAIN ---
def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(CommandHandler("price", price))
    app.add_handler(CommandHandler("setinterval", setinterval))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("help", help_cmd))

    app.run_polling()

if __name__ == "__main__":
    main()
