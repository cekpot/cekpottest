# Chipomatic — Sure-Fix Package (PTB v21)

This version removes old `Updater` API and uses `ApplicationBuilder` (python-telegram-bot v21).

## Deploy (Railway)
1. Upload these files to your GitHub repo and deploy from GitHub on Railway.
2. **Set Start Command to** (only if env var UI keeps failing):
   ```
   env TELEGRAM_BOT_TOKEN=YOUR_TOKEN python bot.py
   ```
   Otherwise, add `TELEGRAM_BOT_TOKEN` in Railway → Variables and just run `python bot.py`.
3. Restart the service.
4. In Telegram, `/start` your bot.

## Notes
- Default: posts every 2 minutes after `/start`.
- Commands: `/start`, `/stop`, `/price`, `/setinterval`, `/status`, `/help`.
- Uses Dexscreener public API (no key needed).