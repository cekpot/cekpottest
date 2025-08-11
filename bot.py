import logging
import re
import aiohttp
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# --------- Logging ---------
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("chipomatic")

# --------- Config ---------
CHAIN = "solana"
PAIR = "fu7dc7yqaepb8qrs9q4tkukss1snejrvxknridtf39bf"  # CHIPS/SOL pair
DEFAULT_INTERVAL = 120  # seconds
JOB_NAME_PREFIX = "price_"

# TEMP: hardcoded token so it runs for sure. Replace with env var later.
TELEGRAM_TOKEN = "8415589355:AAF5iP-kRf7OIe9UavvLqN3UB8lOw1E8i0w"

# --------- Helpers ---------
def parse_interval(text: str):
    m = re.fullmatch(r"\s*(\d+)\s*([smhSMH])\s*", text)
    if not m:
        return None
    qty, unit = int(m.group(1)), m.group(2).lower()
    return qty if unit == "s" else qty * 60 if unit == "m" else qty * 3600

async def fetch_price():
    url = f"https://api.dexscreener.com/latest/dex/pairs/{CHAIN}/{PAIR}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=15) as resp:
                if resp.status != 200:
                    log.warning("Dexscreener HTTP %s", resp.status)
                    return None
                data = await resp.json()
    except Exception as e:
        log.exception("Dexscreener fetch failed: %s", e)
        return None

    pairs = data.get("pairs") or []
    if not pairs:
        return None
    p = pairs[0]
    return {
        "price_usd": p.get("priceUsd"),
        "price_sol": p.get("priceNative"),
        "fdv": p.get("fdv"),
        "liq": (p.get("liquidity") or {}).get("usd"),
        "url": p.get("url") or f"https://dexscreener.com/{CHAIN}/{PAIR}",
        "base": (p.get("baseToken") or {}).get("symbol", "BASE"),
        "quote": (p.get("quoteToken") or {}).get("symbol", "QUOTE"),
    }

async def send_price_job(context: ContextTypes.DEFAULT_TYPE):
    """Job callback: send price to the chat that scheduled it."""
    chat_id = context.job.chat_id
    await send_price_once(context, chat_id)

async def send_price_once(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    """Send one price message immediately."""
    info = await fetch_price()
    if not info:
        await context.bot.send_message(chat_id, "Could not fetch CHIPS price right now.")
        return

    fdv = info["fdv"]
    liq = info["liq"]
    try:
        fdv_txt = f"${int(fdv):,}" if isinstance(fdv, (int, float)) else str(fdv)
    except Exception:
        fdv_txt = str(fdv)
    try:
        liq_txt = f"${int(liq):,}" if isinstance(liq, (int, float)) else str(liq)
    except Exception:
        liq_txt = str(liq)

    msg = (
        f"{info['base']}/{info['quote']} price: ${info['price_usd']} "
        f"({info['price_sol']} {info['quote']})\n"
        f"FDV: {fdv_txt} | Liquidity: {liq_txt}\n"
        f"{info['url']}\n"
        "—\n"
        "Powered by Chipomatic"
    )
    await context.bot.send_message(chat_id, msg)

def schedule_job_for_chat(context: ContextTypes.DEFAULT_TYPE, chat_id: int, interval_sec: int):
    """Cancel any existing job for this chat and schedule a new one."""
    name = JOB_NAME_PREFIX + str(chat_id)
    for j in context.job_queue.get_jobs_by_name(name):
        j.schedule_removal()
    context.job_queue.run_repeating(
        send_price_job, interval=interval_sec, first=interval_sec,  # send next after interval
        chat_id=chat_id, name=name
    )
    log.info("Scheduled repeating job for chat %s every %s sec", chat_id, interval_sec)

# --------- Commands ---------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    schedule_job_for_chat(context, chat_id, DEFAULT_INTERVAL)
    # send one immediately so users see it working
    await send_price_once(context, chat_id)
    await update.message.reply_text(
        f"Chipomatic started! Auto-updates every {DEFAULT_INTERVAL//60} minutes. "
        f"Change with /setinterval (e.g., /setinterval 30s, 2m, 1h)."
    )

async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    name = JOB_NAME_PREFIX + str(chat_id)
    for j in context.job_queue.get_jobs_by_name(name):
        j.schedule_removal()
    await update.message.reply_text("Chipomatic stopped.")

async def cmd_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_price_once(context, update.effective_chat.id)

async def cmd_setinterval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /setinterval 30s | 2m | 1h")
        return
    sec = parse_interval(context.args[0])
    if not sec or sec < 10:
        await update.message.reply_text("Minimum interval is 10 seconds.")
        return
    chat_id = update.effective_chat.id
    schedule_job_for_chat(context, chat_id, sec)
    # send one right away to confirm
    await send_price_once(context, chat_id)
    await update.message.reply_text(f"Interval updated to {sec} seconds.")

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    name = JOB_NAME_PREFIX + str(chat_id)
    jobs = context.job_queue.get_jobs_by_name(name)
    if not jobs:
        await update.message.reply_text("Not running.")
        return
    every = jobs[0].interval
    await update.message.reply_text(f"Running: True\nInterval: {every} sec")

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Chipomatic Commands:\n"
        "/start — start price updates\n"
        "/stop — stop updates\n"
        "/price — get price now\n"
        "/setinterval <time> — 30s, 2m, 1h\n"
        "/status — show current settings\n"
        "/help — this help"
    )

# --------- Main ---------
def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(CommandHandler("price", cmd_price))
    app.add_handler(CommandHandler("setinterval", cmd_setinterval))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("help", cmd_help))

    log.info("Chipomatic starting…")
    app.run_polling()

if __name__ == "__main__":
    main()
