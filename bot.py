import logging
import os
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, JobQueue

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or "YOUR_TELEGRAM_BOT_TOKEN"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

DEFAULT_INTERVAL = 60
JOB_NAME_PREFIX = "price_updates_"

async def send_price_job(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.chat_id
    # Replace with actual price fetching
    await context.bot.send_message(chat_id=chat_id, text="Auto price update here")

def schedule_job_for_chat(context: ContextTypes.DEFAULT_TYPE, chat_id: int, interval_sec: int):
    jq = context.job_queue or context.application.job_queue
    if jq is None:
        raise RuntimeError("JobQueue missing")
    name = JOB_NAME_PREFIX + str(chat_id)
    for j in jq.get_jobs_by_name(name):
        j.schedule_removal()
    jq.run_repeating(send_price_job, interval=interval_sec, first=interval_sec,
                     chat_id=chat_id, name=name)

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    schedule_job_for_chat(context, chat_id, DEFAULT_INTERVAL)
    await update.message.reply_text("Started auto-updates every {} seconds".format(DEFAULT_INTERVAL))

async def cmd_setinterval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /setinterval <seconds>")
        return
    try:
        sec = int(context.args[0])
        if sec < 10:
            await update.message.reply_text("Minimum interval is 10 seconds.")
            return
    except ValueError:
        await update.message.reply_text("Invalid number.")
        return
    chat_id = update.effective_chat.id
    schedule_job_for_chat(context, chat_id, sec)
    await update.message.reply_text(f"Interval set to {sec} seconds.")

def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    # Ensure JobQueue exists
    if app.job_queue is None:
        jq = JobQueue()
        jq.set_application(app)
        jq.start()
        app.job_queue = jq
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("setinterval", cmd_setinterval))
    app.run_polling()

if __name__ == "__main__":
    main()
