#!/bin/sh
# Startup script for Marvin — runs both Telegram and Discord bots in one container.
# Discord bot runs in the background; Telegram bot runs in the foreground.
# Both share the same /data volume and environment variables.

echo "[startup] Starting Marvin Discord bot in background..."
python -u discord_bot.py &
DISCORD_PID=$!
echo "[startup] Discord bot started (PID $DISCORD_PID)"

echo "[startup] Starting Marvin Telegram bot..."
python -u bot.py
