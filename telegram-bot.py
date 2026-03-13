#!/usr/bin/env python3
"""Compatibility launcher for hosting platforms expecting telegram-bot.py."""

from telegram_bot import run_sync


if __name__ == "__main__":
    run_sync()
