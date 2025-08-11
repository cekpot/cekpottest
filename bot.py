import os
import re
import logging
import aiohttp
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# ---------- Logging ----------
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("chipomatic")

# ---------- Config ----------
CHAIN = "solana"
PAIR = "fu7dc7yqaepb8qrs9q4tkukss1snejrvxknridtf39bf"  # CHIPS/SOL pair
DEFAULT_INTERVAL = 120  # seconds
JOB_NAME_PREFIX = "price_"

# Read token from env (Railway Variables)
TELEGRAM_TOKEN = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()

# ---- Debug: print env keys + token snippet ----
def _mask_token(tok: str) -> str:
    if not tok:
        return "<EMPTY>"
    if len(tok) <= 8:
        return "***"
    return f"{tok[:4]}***{tok[-4:]} (len={len(tok)})"

env_keys = sorted(list(os.environ.keys()))
log.info("ENV KEYS (%d): %s", len(env_keys), ", ".join(env_keys[:40]) + (" ..." if len(env_keys) > 40 else ""))
log.info("TELEGRAM_BOT_TOKEN visible? %s", "YES" if TELEGRAM_TOKEN else "NO")
log.info("TELEGRAM_BOT_TOKEN (masked): %s", _mask_token(TELEGRAM_TOKEN))

if not TELEGRAM_TOKEN:
    # Fail fast with a super explicit message so Railway logs show it clearly
    raise SystemExit(
        "Missing/empty TELEGRAM_BOT_TOKEN. "
        "Add it in Railway → Service → Variables, then Restart."
    )

# ---------- Helpers ----------
def parse_interval(text: str):
    """
    Accepts '30s', '2m', '1h'. Returns total seconds or None.
    """
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

async def send_price(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.chat_id
    info = await fetch_price()
    if not info:
        await context.bot.send_message(chat_id, "Could not fetch CHIPS price right now.")
        return

    fdv = info["fdv"]
    liq = info["liq"]
    msg = (
        f"{info['base']}/{info['quote']} price: ${info['price_usd']} "
        f"({info['price_sol']} {info['quote']})\n"
        f"FDV: ${int(fdv):,} | Liquidity: ${int(liq):,}\n"
        f"{info['url']}\n"
        "—\n"
        "Powered by Chipomatic"
    )
    await context.bot.send_message(chat_id, msg)

# ---------- Commands ----------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    # remove old jobs for this chat
    for j in context.job_queue.get_jobs_by_name(JOB_NAME_PREFIX + str(chat_id)):
        j.schedule_removal()
    # schedule repeating
    context.job_queue.run_repeating(
        send_price, interval=DEFAULT_INTERVAL, first=0,
        chat_id=chat_id, name=JOB_NAME_PREFIX + str(chat_id)
    )
    await update.message.reply_text(
        f"Chipomatic started! Sending CHIPS price every {DEFAULT_INTERVAL//60} minutes.\n"
        "Use /setinterval to change frequency."
    )

async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    for j in context.job_queue.get_jobs_by_name(JOB_NAME_PREFIX + str(chat_id)):
        j.schedule_removal()
    await update.message.reply_text("Chipomatic stopped.")

async def cmd_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    info = await fetch_price()
    if not info:
        await update.message.reply_text("Could not fetch CHIPS price right now.")
        return
    fdv = info["fdv"]
    liq = info["liq"]
    msg = (
        f"{info['base']}/{info['quote']} price: ${info['price_usd']} "
        f"({info['price_sol']} {info['quote']})\n"
        f"FDV: ${int(fdv):,} | Liquidity: ${int(liq):,}\n"
        f"{info['url']}\n"
        "—\n"
        "Powered by Chipomatic"
    )
    await update.message.reply_text(msg)

async def cmd_setinterval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /setinterval 30s | 2m | 1h")
        return
    sec = parse_interval(context.args[0])
    if not sec or sec < 10:
        await update.message.reply_text("Minimum interval is 10 seconds.")
        return
    chat_id = update.effective_chat.id
    for j in context.job_queue.get_jobs_by_name(JOB_NAME_PREFIX + str(chat_id)):
        j.schedule_removal()
    context.job_queue.run_repeating(
        send_price, interval=sec, first=0,
        chat_id=chat_id, name=JOB_NAME_PREFIX + str(chat_id)
    )
    await update.message.reply_text(f"Interval updated to {sec} seconds.")

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    jobs = context.job_queue.get_jobs_by_name(JOB_NAME_PREFIX + str(chat_id))
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

# ---------- Main ----------
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