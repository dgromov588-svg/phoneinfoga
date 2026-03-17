#!/usr/bin/env python3
"""Minimal Telegram bot: only Mini App entry point."""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from pathlib import Path
from typing import Optional, Set

from dotenv import load_dotenv
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    MenuButtonWebApp,
    ReplyKeyboardMarkup,
    Update,
    WebAppInfo,
)
from telegram.ext import Application, ContextTypes, MessageHandler, filters


logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

BTN_MINI_APP = "🚀 Mini App"
BTN_OPEN_LINK = "🌐 Открыть Mini App"


class SingleInstanceLock:
    """Cross-platform non-blocking lock to prevent duplicate bot instances."""

    def __init__(self, lock_name: str = "phoneinfoga_telegram_bot.lock"):
        self.lock_path = Path(tempfile.gettempdir()) / lock_name
        self._fh = None

    def __enter__(self) -> "SingleInstanceLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()

    def acquire(self) -> None:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self.lock_path.open("a+", encoding="utf-8")

        self._fh.seek(0, os.SEEK_END)
        if self._fh.tell() == 0:
            self._fh.write("0")
            self._fh.flush()

        try:
            if os.name == "nt":
                import msvcrt

                self._fh.seek(0)
                msvcrt.locking(self._fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl  # type: ignore

                fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self._fh.close()
            self._fh = None
            raise RuntimeError("Telegram bot is already running (single-instance lock active).") from exc

        self._fh.seek(0)
        self._fh.truncate()
        self._fh.write(f"{os.getpid()}\n")
        self._fh.flush()

    def release(self) -> None:
        if not self._fh:
            return

        try:
            if os.name == "nt":
                import msvcrt

                self._fh.seek(0)
                msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl  # type: ignore

                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            self._fh.close()
            self._fh = None

        try:
            self.lock_path.unlink(missing_ok=True)
        except OSError:
            pass


def _parse_allowed_chat_ids(raw: str) -> Set[int]:
    allowed: Set[int] = set()
    for part in (raw or "").split(","):
        value = part.strip()
        if not value:
            continue
        try:
            allowed.add(int(value))
        except ValueError:
            logger.warning("Invalid TELEGRAM_ALLOWED_CHAT_IDS value ignored: %s", value)
    return allowed


def _mini_app_url() -> str:
    return os.getenv("TELEGRAM_MINI_APP_URL", "").strip() or os.getenv("MINI_APP_URL", "").strip()


def _main_menu() -> ReplyKeyboardMarkup:
    mini_app_url = _mini_app_url()
    if mini_app_url:
        keyboard = [[KeyboardButton(BTN_MINI_APP, web_app=WebAppInfo(url=mini_app_url))]]
    else:
        keyboard = [[KeyboardButton(BTN_MINI_APP)]]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True, one_time_keyboard=False, selective=False)


def _inline_open_button(url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton(BTN_OPEN_LINK, url=url)]])


def _is_business_update(update: Update) -> bool:
    if update.business_message or update.edited_business_message:
        return True
    if update.effective_message and getattr(update.effective_message, "business_connection_id", None):
        return True
    return False


def _is_chat_allowed(update: Update, allowed_chat_ids: Set[int]) -> bool:
    if not allowed_chat_ids:
        return True
    if not update.effective_chat:
        return False
    return int(update.effective_chat.id) in allowed_chat_ids


def _is_group_like(chat_type: Optional[str]) -> bool:
    return chat_type in {"group", "supergroup"}


def _should_reply_in_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Avoid noisy replies in groups: respond only on explicit Mini App triggers."""
    chat = update.effective_chat
    message = update.effective_message
    if not chat or not message:
        return False

    chat_type = chat.type
    if chat_type == "private":
        return True

    if not _is_group_like(chat_type):
        return False

    text = (message.text or message.caption or "").strip()
    if not text:
        return False

    lowered = text.lower()
    username = (context.bot.username or "").strip().lower()
    commands = {"/miniapp", "/app", "/start"}

    if lowered in {BTN_MINI_APP.lower(), "mini app", "мини апп", "миниапп"}:
        return True

    if lowered in commands:
        return True

    if username and any(lowered == f"{cmd}@{username}" for cmd in commands):
        return True

    if username and f"@{username}" in lowered:
        return True

    return False


async def _reply_mini_app_entry(update: Update) -> None:
    if not update.effective_message:
        return

    mini_app_url = _mini_app_url()
    if mini_app_url:
        is_private = bool(update.effective_chat and update.effective_chat.type == "private")
        if is_private and not _is_business_update(update):
            await update.effective_message.reply_text("Открой Mini App кнопкой ниже.", reply_markup=_main_menu())
            return
        text = "Открой Mini App по кнопке ниже."
        await update.effective_message.reply_text(
            text,
            reply_markup=_inline_open_button(mini_app_url),
            disable_web_page_preview=True,
        )
        return
    else:
        text = "Mini App URL не настроен. Укажи TELEGRAM_MINI_APP_URL (или MINI_APP_URL) в .env."

    await update.effective_message.reply_text(text, reply_markup=_main_menu())


async def handle_any_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    allowed_chat_ids = context.application.bot_data.get("allowed_chat_ids", set())
    if not _is_chat_allowed(update, allowed_chat_ids):
        if update.effective_message:
            await update.effective_message.reply_text("⛔ Доступ к боту ограничен для этого чата.")
        return
    if not _should_reply_in_chat(update, context):
        return
    await _reply_mini_app_entry(update)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Unhandled error while processing update", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text("⚠️ Ошибка обработки. Нажми кнопку Mini App ещё раз.")
        except Exception:
            logger.exception("Failed to notify user about error")


def build_app(token: str) -> Application:
    app = Application.builder().token(token).build()
    app.add_error_handler(error_handler)
    business_updates = filters.UpdateType.BUSINESS_MESSAGE | filters.UpdateType.EDITED_BUSINESS_MESSAGE
    app.add_handler(MessageHandler(business_updates, handle_any_message))
    app.add_handler(MessageHandler(filters.ALL & ~business_updates, handle_any_message))
    return app


async def configure_menu_button(app: Application) -> None:
    mini_app_url = _mini_app_url()
    if not mini_app_url:
        return
    try:
        await app.bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(text=BTN_MINI_APP, web_app=WebAppInfo(url=mini_app_url))
        )
        logger.info("Bot menu button configured for Mini App")
    except Exception:
        logger.exception("Failed to configure bot menu button")


async def run() -> None:
    load_dotenv()
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set. Add it to .env file.")

    allowed_chat_ids = _parse_allowed_chat_ids(os.getenv("TELEGRAM_ALLOWED_CHAT_IDS", ""))
    app = build_app(token)
    app.bot_data["allowed_chat_ids"] = allowed_chat_ids

    logger.info("Minimal Mini App bot started")
    await app.initialize()
    await app.start()
    await configure_menu_button(app)
    try:
        if app.updater is None:
            raise RuntimeError("Updater is not available; cannot start polling.")
        await app.updater.start_polling()
        while True:
            await asyncio.sleep(3600)
    finally:
        if app.updater:
            await app.updater.stop()
        await app.stop()
        await app.shutdown()


def run_sync() -> None:
    lock = SingleInstanceLock()
    with lock:
        asyncio.run(run())


if __name__ == "__main__":
    run_sync()
