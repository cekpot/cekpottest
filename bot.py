import os
import re
import logging
import aiohttp
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, JobQueue

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

# Token: prefer env, fallback to hardcoded (TEMP). Replace with env later for security.
TELEGRAM_TOKEN = (os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN") or "").strip()
if not TELEGRAM_TOKEN:
    TELEGRAM_TOKEN = "8415589355:AAF5iP-kRf7OIe9UavvLqN3UB8lOw1E8i0w"  # TEMP fallback

# ---------- Helpers ----------
def parse_interval(arg: str) -> int | None:
    """Accepts '10', '30s', '2m', '1h'. Returns seconds or None."""
    arg = (arg or '').strip().lower()
    m = re.fullmatch(r"(\d+)([smh]?)", arg)
    if not m:
        return None
    qty = int(m.group(1))
    unit = m.group(2) or 's'
    if unit == 's':
        return qty
    if unit == 'm':
        return qty * 60
    if unit == 'h':
        return qty * 3600
    return None

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
    chat_id = context.job.chat_id
    await send_price_once(context, chat_id)

async def send_price_once(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    info = await fetch_price()
    if not info:
        await context.bot.send_message(chat_id, "Could not fetch CHIPS price right now.")
        return

    fdv = info["fdv"]
    liq = info["liq"]
    def fmt_money(x):
        try:
            return f"${int(float(x)):,}"
        except Exception:
            return str(x)
    msg = (
        f"CHIPS/SOL price: ${info['price_usd']} ({info['price_sol']} SOL)\n"
        f"FDV: {fmt_money(fdv)} | Liquidity: {fmt_money(liq)}\n"
        f"{info['url']}\n"
        "—\n"
        "Powered by Chipomatic"
    )
    await context.bot.send_message(chat_id, msg)

def schedule_job_for_chat(app_or_ctx, chat_id: int, interval_sec: int):
    """Cancel existing and schedule a new repeating job for this chat."""
    # support being called with either Context or Application
    jq = getattr(app_or_ctx, "job_queue", None)
    if jq is None:
        raise RuntimeError("JobQueue missing (did requirements include [job-queue]?)")
    name = JOB_NAME_PREFIX + str(chat_id)
    for j in jq.get_jobs_by_name(name):
        j.schedule_removal()
    jq.run_repeating(
        send_price_job, interval=interval_sec, first=interval_sec,
        chat_id=chat_id, name=name
    )
    log.info("Scheduled repeating job for chat %s every %s sec", chat_id, interval_sec)

# ---------- Commands ----------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    schedule_job_for_chat(context, chat_id, DEFAULT_INTERVAL)
    await send_price_once(context, chat_id)
    await update.message.reply_text(
        f"Started auto-updates every {DEFAULT_INTERVAL} seconds. "
        "Use /setinterval <seconds|30s|2m|1h>."
    )

async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    jq = context.job_queue or context.application.job_queue
    name = JOB_NAME_PREFIX + str(chat_id)
    if jq:
        for j in jq.get_jobs_by_name(name):
            j.schedule_removal()
    await update.message.reply_text("Stopped auto-updates.")

async def cmd_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_price_once(context, update.effective_chat.id)

async def cmd_setinterval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /setinterval <seconds|30s|2m|1h>")
        return
    sec = parse_interval(context.args[0])
    if not sec or sec < 10:
        await update.message.reply_text("Minimum interval is 10 seconds.")
        return
    chat_id = update.effective_chat.id
    schedule_job_for_chat(context, chat_id, sec)
    await send_price_once(context, chat_id)
    await update.message.reply_text(f"Interval set to {sec} seconds.")

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    jq = context.job_queue or context.application.job_queue
    name = JOB_NAME_PREFIX + str(chat_id)
    jobs = jq.get_jobs_by_name(name) if jq else []
    if not jobs:
        await update.message.reply_text("Not running.")
        return
    await update.message.reply_text(f"Running: True\nInterval: {jobs[0].interval} sec")

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Chipomatic Commands:\n"
        "/start — start price updates\n"
        "/stop — stop updates\n"
        "/price — get price now\n"
        "/setinterval <time> — 10, 30s, 2m, 1h\n"
        "/status — show current settings\n"
        "/help — this help"
    )

# ---------- Main ----------
def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    # Ensure JobQueue exists (requires PTB [job-queue] extra)
    if app.job_queue is None:
        jq = JobQueue()
        jq.set_application(app)
        jq.start()
        app.job_queue = jq

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
