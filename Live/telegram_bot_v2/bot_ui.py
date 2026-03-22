import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CommandHandler, CallbackQueryHandler, ContextTypes
from bot_core import bot_state, start_bot_core

async def tg_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("?? 状態確認", callback_data="status")],
        [InlineKeyboardButton("?? 本番開始", callback_data="confirm_live")],
        [InlineKeyboardButton("? DRY停止", callback_data="set_dry")],
        [InlineKeyboardButton("?? 緊急停止", callback_data="kill")]
    ]

    await update.message.reply_text(
        "?? TradingAI 本番操作パネル",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def tg_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "status":
        await query.edit_message_text(
            f"?? 状態\n"
            f"稼働中: {bot_state.running}\n"
            f"モード: {'DRY' if bot_state.dry_run else '本番'}"
        )

    elif query.data == "confirm_live":
        bot_state.dry_run = False
        await query.edit_message_text("?? 本番モードに切替しました")
        start_bot_core()

    elif query.data == "set_dry":
        bot_state.dry_run = True
        await query.edit_message_text("? DRYモードにしました")

    elif query.data == "kill":
        bot_state.running = False
        bot_state.dry_run = True
        await query.edit_message_text("?? 緊急停止しました")

def register_handlers(app):
    app.add_handler(CommandHandler("menu", tg_menu))
    app.add_handler(CallbackQueryHandler(tg_button))
