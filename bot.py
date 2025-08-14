import os
import re
import time
import logging
from typing import Dict, Any, Optional, List

import aiohttp
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes, JobQueue
)

# ---------- Logging ----------
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("chipomatic-watch")

# ---------- Config ----------
CHAIN = "solana"
DEFAULT_PAIR = "fu7dc7yqaepb8qrs9q4tkukss1snejrvxknridtf39bf"  # CHIPS/SOL pair
DEFAULT_INTERVAL = 10  # seconds for trade polling
DEFAULT_MIN_USD = 0.0  # min trade size to alert

# Token: env first, fallback (TEMP) to hardcoded so it runs immediately
TELEGRAM_TOKEN = (os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN") or "").strip()
if not TELEGRAM_TOKEN:
    TELEGRAM_TOKEN = "8415589355:AAF5iP-kRf7OIe9UavvLqN3UB8lOw1E8i0w"  # TEMP. Replace with env later.

# Per-chat watch state
WATCH: Dict[int, Dict[str, Any]] = {}
JOB_NAME_PREFIX = "watch_"

# ---------- HTTP helpers ----------
async def get_json(url: str, session: Optional[aiohttp.ClientSession] = None) -> Optional[Dict[str, Any]]:
    try:
        if session is None:
            async with aiohttp.ClientSession() as s:
                async with s.get(url, timeout=15) as resp:
                    if resp.status != 200:
                        log.warning("HTTP %s for %s", resp.status, url)
                        return None
                    return await resp.json()
        else:
            async with session.get(url, timeout=15) as resp:
                if resp.status != 200:
                    log.warning("HTTP %s for %s", resp.status, url)
                    return None
                return await resp.json()
    except Exception as e:
        log.exception("GET %s failed: %s", url, e)
        return None

async def fetch_latest_price(pair: str) -> Optional[Dict[str, Any]]:
    url = f"https://api.dexscreener.com/latest/dex/pairs/{CHAIN}/{pair}"
    data = await get_json(url)
    if not data:
        return None
    pairs = data.get("pairs") or []
    if not pairs:
        return None
    p = pairs[0]
    return {
        "price_usd": p.get("priceUsd"),
        "price_native": p.get("priceNative"),
        "url": p.get("url") or f"https://dexscreener.com/{CHAIN}/{pair}",
        "base": (p.get("baseToken") or {}).get("symbol", "BASE"),
        "quote": (p.get("quoteToken") or {}).get("symbol", "QUOTE"),
    }

async def fetch_latest_trades(pair: str, limit: int = 10) -> List[Dict[str, Any]]:
    """
    Try Dexscreener latest-trades endpoint and normalize the data.
    We return a list of dicts with: id, type, amountUsd, amountBase, priceUsd, ts, txId, wallet.
    """
    url = f"https://api.dexscreener.com/v1/dex/trades/latest?chain={CHAIN}&pairAddress={pair}"
    data = await get_json(url)
    trades: List[Dict[str, Any]] = []

    raw = []
    if data:
        raw = data.get("trades") if isinstance(data, dict) else data
        if raw is None:
            raw = []

    for t in raw:
        ttype = (t.get("type") or t.get("side") or "").upper()  # BUY/SELL
        txid = t.get("txId") or t.get("transactionId") or t.get("id")
        ts = t.get("timestamp") or t.get("ts") or t.get("time")
        price_usd = t.get("priceUsd") or t.get("price") or t.get("usdPrice")
        amount_usd = t.get("amountUsd") or t.get("usdValue") or t.get("valueUsd")
        amount_base = t.get("amount") or t.get("baseAmount") or t.get("amountBase")
        wallet = t.get("maker") or t.get("wallet") or t.get("address") or ""

        # Normalize timestamp to seconds (int)
        if ts is None:
            ts_sec = None
        else:
            try:
                ts = float(ts)
                ts_sec = int(ts / 1000) if ts > 1e12 else int(ts)
            except Exception:
                ts_sec = None

        # Normalize numbers
        def to_float(v):
            try:
                return float(v)
            except Exception:
                return None

        trades.append({
            "id": txid or f"{ts_sec}-{amount_usd}-{amount_base}",
            "type": ttype or "TRADE",
            "amountUsd": to_float(amount_usd),
            "amountBase": to_float(amount_base),
            "priceUsd": to_float(price_usd) if price_usd is not None else None,
            "ts": ts_sec,
            "txId": txid,
            "wallet": wallet,
        })

    trades.sort(key=lambda x: x.get("ts") or 0)
    return trades

# ---------- Formatting ----------
def fmt_money(x: Any) -> str:
    if x is None:
        return "n/a"
    try:
        return f"${float(x):,.2f}"
    except Exception:
        return str(x)

def fmt_amount(x: Any) -> str:
    if x is None:
        return "n/a"
    try:
        # for CHIPS we usually want whole tokens
        return f"{float(x):,.0f}"
    except Exception:
        return str(x)

# ---------- Job: watch trades ----------
async def watch_job(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.chat_id
    st = WATCH.get(chat_id)
    if not st or not st.get("on"):
        return

    pair = st["pair"]
    min_usd = st["min_usd"]
    last_seen = st.get("last_seen")

    trades = await fetch_latest_trades(pair)
    if not trades:
        return

    new_items = []
    for tr in trades:
        key = tr.get("id") or tr.get("ts")
        if key is None:
            continue
        if last_seen is None:
            # initialize cursor on first run (skip history)
            last_seen = key
            continue
        if key > last_seen:
            new_items.append(tr)

    if new_items:
        st["last_seen"] = new_items[-1].get("id") or new_items[-1].get("ts")
        WATCH[chat_id] = st

    for tr in new_items:
        if tr["amountUsd"] is not None and tr["amountUsd"] < min_usd:
            continue

        price_info = await fetch_latest_price(pair)
        price_line = ""
        if price_info:
            price_line = f"Price now: ${price_info['price_usd']} ({price_info['price_native']} {price_info['quote']})\n{price_info['url']}"

        side = tr["type"] or "TRADE"
        msg = (
            f"{side}\n"
            f"Size: {fmt_amount(tr['amountBase'])} tokens ({fmt_money(tr['amountUsd'])})\n"
            f"Trade price: {fmt_money(tr['priceUsd'])}\n"
            f"{price_line}"
        )
        await context.bot.send_message(chat_id, msg)

# ---------- Commands ----------
def parse_time_arg(arg: str) -> Optional[int]:
    arg = (arg or "").strip().lower()
    m = re.fullmatch(r"(\d+)([smh]?)", arg)
    if not m:
        return None
    qty = int(m.group(1))
    unit = m.group(2) or "s"
    return qty if unit == "s" else qty * 60 if unit == "m" else qty * 3600

def ensure_jobqueue(app):
    if app.job_queue is None:
        jq = JobQueue()
        jq.set_application(app)
        jq.start()
        app.job_queue = jq

def name_for(chat_id: int) -> str:
    return JOB_NAME_PREFIX + str(chat_id)

def schedule_watch(app_or_ctx, chat_id: int, interval_sec: int):
    jq = getattr(app_or_ctx, "job_queue", None)
    if jq is None:
        raise RuntimeError("JobQueue missing; did you install python-telegram-bot[job-queue]?")
    name = name_for(chat_id)
    for j in jq.get_jobs_by_name(name):
        j.schedule_removal()
    jq.run_repeating(watch_job, interval=interval_sec, first=0, chat_id=chat_id, name=name)
    log.info("Scheduled watch job for chat %s every %ss", chat_id, interval_sec)

async def cmd_watch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    subcmd = (context.args[0].lower() if context.args else "status")
    st = WATCH.setdefault(chat_id, {"on": False, "pair": DEFAULT_PAIR, "interval": DEFAULT_INTERVAL, "min_usd": DEFAULT_MIN_USD, "last_seen": None})

    if subcmd in ("on", "start"):
        st["on"] = True
        WATCH[chat_id] = st
        schedule_watch(context, chat_id, st["interval"])
        await update.message.reply_text(f"Trade watch ON for {st['pair']} every {st['interval']}s. Min ${st['min_usd']}.")
    elif subcmd in ("off", "stop"):
        st["on"] = False
        WATCH[chat_id] = st
        jq = context.job_queue or context.application.job_queue
        if jq:
            for j in jq.get_jobs_by_name(name_for(chat_id)):
                j.schedule_removal()
        await update.message.reply_text("Trade watch OFF.")
    else:
        await update.message.reply_text(
            "Usage: /watch on | off | status\n"
            "Also see /freq, /min, /pair"
        )

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    st = WATCH.get(chat_id) or {}
    await update.message.reply_text(
        "Status:\n"
        f"on: {st.get('on', False)}\n"
        f"pair: {st.get('pair', DEFAULT_PAIR)}\n"
        f"interval: {st.get('interval', DEFAULT_INTERVAL)}s\n"
        f"min_usd: ${st.get('min_usd', DEFAULT_MIN_USD)}\n"
        f"last_seen: {st.get('last_seen')}"
    )

async def cmd_freq(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    st = WATCH.setdefault(chat_id, {"on": False, "pair": DEFAULT_PAIR, "interval": DEFAULT_INTERVAL, "min_usd": DEFAULT_MIN_USD, "last_seen": None})
    if not context.args:
        await update.message.reply_text("Usage: /freq <10|30s|2m|1h>")
        return
    sec = parse_time_arg(context.args[0])
    if not sec or sec < 5:
        await update.message.reply_text("Minimum interval is 5 seconds.")
        return
    st["interval"] = sec
    WATCH[chat_id] = st
    if st["on"]:
        schedule_watch(context, chat_id, sec)
    await update.message.reply_text(f"Polling interval set to {sec}s.")

async def cmd_min(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    st = WATCH.setdefault(chat_id, {"on": False, "pair": DEFAULT_PAIR, "interval": DEFAULT_INTERVAL, "min_usd": DEFAULT_MIN_USD, "last_seen": None})
    if not context.args:
        await update.message.reply_text("Usage: /min <usd> (e.g., /min 25)")
        return
    try:
        usd = float(context.args[0])
    except ValueError:
        await update.message.reply_text("Invalid number.")
        return
    st["min_usd"] = usd
    WATCH[chat_id] = st
    await update.message.reply_text(f"Minimum trade size set to ${usd}.")

async def cmd_pair(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    st = WATCH.setdefault(chat_id, {"on": False, "pair": DEFAULT_PAIR, "interval": DEFAULT_INTERVAL, "min_usd": DEFAULT_MIN_USD, "last_seen": None})
    if not context.args:
        await update.message.reply_text(f"Usage: /pair <address>\nCurrent: {st['pair']}")
        return
    st["pair"] = context.args[0]
    st["last_seen"] = None
    WATCH[chat_id] = st
    await update.message.reply_text(f"Pair set to {st['pair']} and cursor reset.")

async def cmd_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    st = WATCH.get(chat_id) or {"pair": DEFAULT_PAIR}
    p = await fetch_latest_price(st["pair"])
    if not p:
        await update.message.reply_text("Could not fetch price.")
        return
    await update.message.reply_text(
        f"{p['base']}/{p['quote']} price: ${p['price_usd']} ({p['price_native']} {p['quote']})\n{p['url']}"
    )

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Trade Alerts:\n"
        "/watch on|off — enable/disable buy/sell alerts\n"
        "/freq <10|30s|2m|1h> — polling interval\n"
        "/min <usd> — minimum USD size to alert\n"
        "/pair <address> — change pair\n"
        "/status — show settings\n"
        "/price — current price\n"
    )

# ---------- Main ----------
def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    if app.job_queue is None:
        jq = JobQueue()
        jq.set_application(app)
        jq.start()
        app.job_queue = jq

    app.add_handler(CommandHandler("watch", cmd_watch))
    app.add_handler(CommandHandler("freq", cmd_freq))
    app.add_handler(CommandHandler("min", cmd_min))
    app.add_handler(CommandHandler("pair", cmd_pair))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("price", cmd_price))
    app.add_handler(CommandHandler("help", cmd_help))

    log.info("Chipomatic Watch starting…")
    app.run_polling()

if __name__ == "__main__":
    main()
