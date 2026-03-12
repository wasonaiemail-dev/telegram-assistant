import os
import logging
from openai import OpenAI
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, filters, ContextTypes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
ALLOWED_USER_ID = int(os.environ["ALLOWED_USER_ID"])

client = OpenAI()

conversation_history = {}

SYSTEM_PROMPT = """You are a personal assistant accessible via Telegram. You are helpful, concise, and friendly.

You help with:
- Scheduling and calendar management
- To-do lists and task tracking
- Daily briefings and reminders
- Note taking and saving ideas
- Budget and expense tracking
- Habit and goal tracking
- Suggesting replies to messages
- General questions and research

Keep responses conversational and to the point. When the user asks you to remember something, confirm that you have.
If a task requires a feature not yet built (like actually adding to Google Calendar), let the user know it's coming soon and note down their request."""


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ALLOWED_USER_ID:
        return
    await update.message.reply_text(
        "Hey! I'm your personal assistant. I'm ready to help with your calendar, tasks, notes, habits, budget, and more.\n\nJust talk to me naturally — what's on your mind?"
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if user_id != ALLOWED_USER_ID:
        logger.warning(f"Unauthorized access attempt from user {user_id}")
        return

    user_message = update.message.text
    logger.info(f"Received message: {user_message}")

    if user_id not in conversation_history:
        conversation_history[user_id] = []

    conversation_history[user_id].append({
        "role": "user",
        "content": user_message
    })

    if len(conversation_history[user_id]) > 20:
        conversation_history[user_id] = conversation_history[user_id][-20:]

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    try:
        messages = [{"role": "system", "content": SYSTEM_PROMPT}] + conversation_history[user_id]

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            max_tokens=500,
            temperature=0.7
        )

        assistant_message = response.choices[0].message.content

        conversation_history[user_id].append({
            "role": "assistant",
            "content": assistant_message
        })

        await update.message.reply_text(assistant_message)

    except Exception as e:
        logger.error(f"Error calling OpenAI: {e}")
        await update.message.reply_text(
            "Sorry, I ran into an issue processing that. Please try again in a moment."
        )


async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ALLOWED_USER_ID:
        return
    conversation_history.clear()
    await update.message.reply_text("Memory cleared — starting fresh!")


def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("clear", clear))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot is running...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
