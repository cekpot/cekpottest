# Chipomatic — CHIPS Price Bot

A Telegram bot that posts $CHIPS price in USD + SOL, FDV, and Liquidity every X minutes.

## Features
- Default 2-minute updates
- Commands:
  - `/start` — start updates
  - `/stop` — stop updates
  - `/price` — get price instantly
  - `/setinterval <time>` — change frequency (e.g., 30s, 2m, 1h)
  - `/status` — see current settings
  - `/help` — show commands

## Deploy on Railway
1. Create a Telegram bot via [@BotFather](https://t.me/BotFather) and copy the token.
2. Push this code to a GitHub repo.
3. Go to [Railway](https://railway.app/) → **New Project** → **Deploy from GitHub**.
4. Add environment variable:
   - `TELEGRAM_BOT_TOKEN` = your bot token
5. Deploy, then add the bot to your group and use `/start`.

## Powered by Chipomatic
