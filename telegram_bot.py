#!/usr/bin/env python3
"""Telegram bot for quick phone checks using this workspace search engine."""

from __future__ import annotations

import asyncio
import contextlib
import html
import json
import logging
import os
import re
import sqlite3
import tempfile
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import quote, urlencode

from dotenv import load_dotenv
import requests
from PIL import Image, ImageEnhance, ImageFilter, ImageOps
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from universal_search_system import universal_search
from tg_catalog_db import catalog_stats, random_catalog, search_catalog, top_catalog

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen import canvas

    _REPORTLAB_AVAILABLE = True
except ImportError:
    _REPORTLAB_AVAILABLE = False

try:
    import gspread
    from google.oauth2.service_account import Credentials

    _GSHEETS_AVAILABLE = True
except ImportError:
    _GSHEETS_AVAILABLE = False


logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)
# Prevent bot token leakage in logs (httpx logs full request URLs by default).
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

BTN_PHONE = "📞 Поиск по номеру"
BTN_PHOTO = "🖼 Поиск по фото"
BTN_PHOTO_ENHANCE = "✨ Улучшить фото"
BTN_ID = "🆔 Мой ID"
BTN_SOURCE = "📦 Источники"
BTN_GREEN_ORDER = "🟢 Заказ у зелёных"
BTN_BACK = "⬅️ Назад"
BTN_HOME = "🏠 Главное меню"
BTN_TG = "👤 Ник в Telegram"
BTN_TG_CATALOG = "💬 Каталог Telegram"
BTN_FSSP = "⚖️ Проверка ФССП"
BTN_REPORT_767 = "📊 Отчёт 767"
BTN_ADMIN = "🛠 Панель администратора"
BTN_HELP = "ℹ️ Помощь"
_TG_USERNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{4,31}$")
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_REPORT_FONT_NAME: Optional[str] = None
REPORT_767_TEAMS: Tuple[str, ...] = ("kizaru1312", "apathy7", "stil1x315")
REPORT_767_DB_PATH = "reports_767.db"
MODE_REPORT_767_TEAM = "report767_team"
MODE_REPORT_767_NUMBERS_TO_CHECK = "report767_numbers_to_check"
MODE_REPORT_767_POSITIVES = "report767_positives"
MODE_REPORT_767_ACTIVE = "report767_active"
MODE_REPORT_767_VBROS = "report767_vbros"
MODE_REPORT_767_PREDLOG = "report767_predlog"
MODE_REPORT_767_SOGLASIY = "report767_soglasiy"
MODE_REPORT_767_ACCESS_ADD = "report767_access_add"
MODE_REPORT_767_ACCESS_REMOVE = "report767_access_remove"
MODE_ADMIN_ROLE_ADD_HEAD = "admin_role_add_head"
MODE_ADMIN_ROLE_ADD_TEAM = "admin_role_add_team"
MODE_ADMIN_ROLE_REMOVE = "admin_role_remove"
MODE_PHOTO_SEARCH = "photo_search"
MODE_PHOTO_ENHANCE = "photo_enhance"
MODE_SOURCE_PICK = "source_pick"
MODE_SOURCE_ADD = "source_add"
MODE_SOURCE_REMOVE = "source_remove"
MODE_GREEN_ORDER_DONOR = "green_order_donor"
MODE_GREEN_ORDER_NAME = "green_order_name"
MODE_GREEN_ORDER_DOB = "green_order_dob"
MODE_GREEN_ORDER_COUNT = "green_order_count"
MODE_GREEN_ORDER_VK = "green_order_vk"
_GS_WORKSHEET = None
_GS_ERROR: Optional[str] = None
_RUNTIME_ADMIN_CHAT_IDS: Set[int] = set()


def _main_menu(include_admin: bool = False) -> ReplyKeyboardMarkup:
    keyboard = [
        [KeyboardButton(BTN_PHONE), KeyboardButton(BTN_PHOTO)],
        [KeyboardButton(BTN_PHOTO_ENHANCE), KeyboardButton(BTN_TG)],
        [KeyboardButton(BTN_TG_CATALOG), KeyboardButton(BTN_FSSP)],
        [KeyboardButton(BTN_REPORT_767), KeyboardButton(BTN_SOURCE)],
        [KeyboardButton(BTN_GREEN_ORDER), KeyboardButton(BTN_HELP)],
        [KeyboardButton(BTN_ID)],
    ]
    if include_admin:
        keyboard.append([KeyboardButton(BTN_ADMIN)])
    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
        one_time_keyboard=False,
        selective=False,
    )


def _back_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(BTN_BACK), KeyboardButton(BTN_HOME)]],
        resize_keyboard=True,
        one_time_keyboard=False,
        selective=False,
    )


def _ui_card(title: str, lines: List[str], hint: Optional[str] = None) -> str:
    parts: List[str] = [f"✨ <b>{title}</b>"]
    if lines:
        parts.append("")
        for line in lines:
            cleaned = line.strip()
            if cleaned:
                parts.append(f"• {cleaned}")
    if hint:
        parts.extend(["", f"↩️ {hint.strip()}"])
    return "\n".join(parts)


def _back_hint() -> str:
    return "Нажми <b>⬅️ Назад</b> или <b>🏠 Главное меню</b>."


def _report767_team_inline() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("kizaru1312", callback_data="report767:team:kizaru1312"),
                InlineKeyboardButton("apathy7", callback_data="report767:team:apathy7"),
            ],
            [InlineKeyboardButton("stil1x315", callback_data="report767:team:stil1x315")],
        ]
    )


async def _error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Global error handler to prevent handler exceptions from crashing the bot."""
    err = getattr(context, "error", None)
    logger.error("Unhandled exception while processing update", exc_info=err)
    try:
        if isinstance(update, Update) and update.effective_message:
            await update.effective_message.reply_text(
                "⚠️ Произошла ошибка при обработке сообщения. Попробуйте ещё раз позже."
            )
    except Exception:
        logger.exception("Failed to notify user about error")


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

        # Ensure file has at least one byte for byte-range locking on Windows.
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
                import importlib

                fcntl = importlib.import_module("fcntl")  # type: ignore[reportMissingImports]
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
                import importlib

                fcntl = importlib.import_module("fcntl")  # type: ignore[reportMissingImports]
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
    """Parse comma-separated chat IDs from env variable."""
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


def _parse_admin_chat_ids(raw: str) -> Set[int]:
    """Parse comma-separated admin chat IDs from env variable."""
    admins: Set[int] = set()
    for part in (raw or "").split(","):
        value = part.strip()
        if not value:
            continue
        try:
            admins.add(int(value))
        except ValueError:
            logger.warning("Invalid TELEGRAM_ADMIN_CHAT_IDS value ignored: %s", value)
    return admins


def _parse_optional_int(raw: str) -> Optional[int]:
    value = (raw or "").strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        logger.warning("Invalid integer value ignored: %s", value)
        return None


def _is_chat_allowed(update: Update, allowed_chat_ids: Set[int]) -> bool:
    if not allowed_chat_ids:
        return True
    if not update.effective_chat:
        return False
    return int(update.effective_chat.id) in allowed_chat_ids


def _is_admin_chat(update: Update, admin_chat_ids: Set[int]) -> bool:
    if not admin_chat_ids:
        return False
    if not update.effective_chat:
        return False
    return int(update.effective_chat.id) in admin_chat_ids


def _is_runtime_admin_chat_id(chat_id: Optional[int]) -> bool:
    if chat_id is None:
        return False
    return int(chat_id) in _RUNTIME_ADMIN_CHAT_IDS


def _main_menu_for_update(update: Update) -> ReplyKeyboardMarkup:
    chat_id = int(update.effective_chat.id) if update.effective_chat else None
    return _main_menu(include_admin=_is_runtime_admin_chat_id(chat_id))


async def _deny_if_not_allowed(update: Update, allowed_chat_ids: Set[int]) -> bool:
    if _is_chat_allowed(update, allowed_chat_ids):
        return False
    if update.message:
        await update.message.reply_text("⛔ Доступ к боту ограничен для этого чата.")
    return True


def _compact_lines(lines: List[str], max_len: int = 4000) -> str:
    """Join lines and cap output to Telegram safe text length."""
    text = "\n".join(lines)
    if len(text) <= max_len:
        return text
    return f"{text[: max_len - 15]}\n...\n(обрезано)"


async def _reply_menu_text(
    update: Update,
    text: str,
    reply_markup: Optional[ReplyKeyboardMarkup] = None,
) -> None:
    if not update.message:
        return
    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
        reply_markup=reply_markup or _main_menu_for_update(update),
    )


def _clear_input_state(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop("input_mode", None)
    context.user_data.pop("report767_draft", None)
    context.user_data.pop("green_order", None)


def _safe_get(d: Dict[str, Any], *keys: str, default: Any = "—") -> Any:
    current: Any = d
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


def _strip_html_for_pdf(value: str) -> str:
    text = (value or "").replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
    text = re.sub(r"</(p|div|h\d|li)>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<li[^>]*>", "• ", text, flags=re.IGNORECASE)
    text = _HTML_TAG_RE.sub("", text)
    text = html.unescape(text)
    text = text.replace("\r", "")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _get_report_font_name() -> str:
    global _REPORT_FONT_NAME
    if _REPORT_FONT_NAME:
        return _REPORT_FONT_NAME

    if not _REPORTLAB_AVAILABLE:
        _REPORT_FONT_NAME = "Helvetica"
        return _REPORT_FONT_NAME

    font_path_candidates = [
        os.getenv("REPORTS_FONT_PATH", "").strip(),
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "C:\\Windows\\Fonts\\arial.ttf",
    ]

    for font_path in font_path_candidates:
        if not font_path:
            continue
        if not os.path.isfile(font_path):
            continue
        try:
            pdfmetrics.registerFont(TTFont("ReportUnicode", font_path))
            _REPORT_FONT_NAME = "ReportUnicode"
            return _REPORT_FONT_NAME
        except Exception:
            continue

    _REPORT_FONT_NAME = "Helvetica"
    return _REPORT_FONT_NAME


def _wrap_text_for_pdf(text: str, max_chars: int = 100) -> List[str]:
    out: List[str] = []
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line:
            out.append("")
            continue
        while len(line) > max_chars:
            out.append(line[:max_chars])
            line = line[max_chars:]
        out.append(line)
    return out


def _normalize_pdf_text(value: str, font_name: str) -> str:
    if font_name == "Helvetica":
        # Core Helvetica font has very limited unicode support.
        return (value or "").encode("latin-1", "replace").decode("latin-1")
    return value or ""


def _build_pdf_report(title: str, html_body: str) -> Dict[str, str]:
    if not _REPORTLAB_AVAILABLE:
        return {"ok": "0", "error": "reportlab is not installed"}

    reports_dir = os.getenv("REPORTS_PUBLIC_DIR", "").strip()
    reports_base_url = os.getenv("REPORTS_BASE_URL", "").strip().rstrip("/")
    if not reports_dir or not reports_base_url:
        return {"ok": "0", "error": "REPORTS_PUBLIC_DIR/REPORTS_BASE_URL not configured"}

    try:
        os.makedirs(reports_dir, exist_ok=True)
    except OSError as exc:
        return {"ok": "0", "error": f"Cannot create reports dir: {exc}"}

    filename = f"report_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.pdf"
    report_path = os.path.join(reports_dir, filename)
    report_url = f"{reports_base_url}/{filename}"

    font_name = _get_report_font_name()
    plain_body = _strip_html_for_pdf(html_body)
    lines = _wrap_text_for_pdf(plain_body, max_chars=105)

    try:
        pdf = canvas.Canvas(report_path, pagesize=A4)
        width, height = A4
        left = 40
        y = height - 45

        pdf.setTitle(_normalize_pdf_text(title, font_name))
        pdf.setAuthor("OSINT5KIZARU Bot")

        pdf.setFont(font_name, 13)
        pdf.drawString(left, y, _normalize_pdf_text(title[:140], font_name))
        y -= 24

        pdf.setFont(font_name, 10)
        for line in lines:
            if y < 45:
                pdf.showPage()
                pdf.setFont(font_name, 10)
                y = height - 45
            pdf.drawString(left, y, _normalize_pdf_text(line, font_name))
            y -= 14

        pdf.save()
    except Exception as exc:
        return {"ok": "0", "error": f"PDF generation failed: {exc}"}

    return {"ok": "1", "path": report_path, "url": report_url}


async def _reply_with_pdf_report(
    update: Update,
    title: str,
    html_body: str,
    include_text: bool = True,
) -> None:
    if not update.message:
        return

    if include_text:
        await update.message.reply_text(
            html_body,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )

    report = _build_pdf_report(title=title, html_body=html_body)
    if report.get("ok") == "1":
        report_url = report.get("url", "")
        await update.message.reply_text(
            f"📄 <a href=\"{report_url}\">Скачать PDF-отчет</a>",
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    else:
        logger.warning("PDF report unavailable: %s", report.get("error", "unknown"))
        await update.message.reply_text("⚠️ PDF-отчет недоступен (временная ошибка).")


def _format_result(payload: Dict[str, Any]) -> str:
    if not payload.get("valid"):
        err = payload.get("error", "Не удалось обработать номер")
        return f"❌ {err}"

    basic = _safe_get(payload, "results", "basic", default={})
    owner = _safe_get(payload, "results", "owner", default={})
    breaches = _safe_get(payload, "results", "data_breaches", default={})
    search_engines = _safe_get(payload, "results", "search_engines", default={})
    social_platforms = _safe_get(payload, "results", "social_platforms", default={})

    location = _safe_get(basic, "location_ru") or _safe_get(basic, "location_en") or _safe_get(basic, "country")
    region_code = _safe_get(basic, "region_code")
    country_code = _safe_get(basic, "country_code")
    carrier_name = _safe_get(basic, "carrier")
    if not carrier_name:
        carrier_name = "—"

    lines = [
        "✅ <b>Результат проверки</b>",
        f"📞 Ввод: <code>{payload.get('input', '—')}</code>",
        f"🌍 E.164: <code>{payload.get('formatted', '—')}</code>",
        "",
        "<b>Базовая информация</b>",
        f"• Страна/регион: {location or '—'} ({region_code or '—'})",
        f"• Код страны: {country_code or '—'}",
        f"• Оператор: {carrier_name}",
        f"• Международный формат: <code>{_safe_get(basic, 'international_format')}</code>",
        f"• Национальный формат: <code>{_safe_get(basic, 'national_format')}</code>",
    ]

    if isinstance(owner, dict) and owner.get("found"):
        lines.extend([
            "",
            "<b>Локальный справочник</b>",
            f"• Найдено совпадений: {owner.get('matches', 0)}",
        ])
        candidates = owner.get("candidates") or []
        for i, item in enumerate(candidates[:3], start=1):
            name = item.get("name") or "—"
            city = item.get("city") or "—"
            category = item.get("category") or "—"
            lines.append(f"  {i}. {name} | {city} | {category}")
    else:
        lines.extend([
            "",
            "<b>Локальный справочник</b>",
            "• Совпадений не найдено",
        ])

    if isinstance(breaches, dict):
        found = breaches.get("found")
        matches = breaches.get("matches", 0)
        lines.extend([
            "",
            "<b>Проверка утечек (редактированный вывод)</b>",
            f"• Обнаружено: {'да' if found else 'нет'}",
            f"• Количество записей: {matches}",
        ])

    if isinstance(search_engines, dict) and search_engines:
        lines.append("")
        lines.append("<b>Поисковые системы</b>")
        for engine in ["google", "yandex", "bing", "duckduckgo", "startpage", "yahoo"]:
            data = search_engines.get(engine)
            if not isinstance(data, dict):
                continue
            title = data.get("engine") or engine
            url = data.get("search_url") or data.get("url") or ""
            if url:
                lines.append(f"• {title}: {url}")

    if isinstance(social_platforms, dict) and social_platforms:
        lines.append("")
        lines.append("<b>Соцсети/мессенджеры</b>")
        for platform in [
            "telegram",
            "whatsapp",
            "vk",
            "facebook",
            "instagram",
            "twitter",
            "linkedin",
            "tiktok",
            "reddit",
            "discord",
        ]:
            data = social_platforms.get(platform)
            if not isinstance(data, dict):
                continue
            title = data.get("platform") or platform
            url = (
                data.get("search_url")
                or data.get("direct_url")
                or data.get("chat_url")
                or data.get("profile_url")
                or ""
            )
            if url:
                lines.append(f"• {title}: {url}")

    ru_sources = payload.get("results", {}).get("ru_sources", [])
    if isinstance(ru_sources, list) and ru_sources:
        lines.append("")
        lines.append("<b>Российские источники</b>")
        for source in ru_sources:
            name = source.get("name")
            url = source.get("url")
            desc = source.get("description")
            if name and url:
                label = f"<a href=\"{url}\">{name}</a>"
                if desc:
                    label = f"{label} — {desc}"
                lines.append(f"• {label}")

    return _compact_lines(lines)


def _format_ip_result(payload: Dict[str, Any]) -> str:
    if payload.get("valid") is False:
        return f"❌ {payload.get('error', 'Некорректный IP')}"

    lines = [
        "✅ <b>IP lookup</b>",
        f"🌐 IP: <code>{payload.get('ip', '—')}</code>",
        f"📍 Страна: {payload.get('country', '—')}",
        f"🏙 Город: {payload.get('city', '—')}",
        f"🛰 Провайдер/ASN: {payload.get('org') or payload.get('asn', '—')}",
    ]
    return _compact_lines(lines)


def _format_email_result(payload: Dict[str, Any]) -> str:
    if payload.get("valid") is False:
        return f"❌ {payload.get('error', 'Некорректный email')}"

    lines = [
        "✅ <b>Email check</b>",
        f"📧 Email: <code>{payload.get('email', '—')}</code>",
        f"• Синтаксис: {'OK' if payload.get('valid_format') else 'ошибка'}",
        f"• Домен: <code>{payload.get('domain', '—')}</code>",
        f"• MX записи: {'есть' if payload.get('has_mx') else 'нет/неизвестно'}",
    ]
    return _compact_lines(lines)


def _parse_fssp_input(raw: str) -> Dict[str, str]:
    """Parse /fssp input: 'Фамилия Имя Отчество;YYYY-MM-DD;77'.

    Birth date and region are optional, but FIO must contain at least 2 words.
    """
    parts = [p.strip() for p in (raw or "").split(";")]
    fio = parts[0] if parts else ""
    birth_date = parts[1] if len(parts) > 1 and parts[1] else ""
    region = parts[2] if len(parts) > 2 and parts[2] else "77"

    words = [w for w in fio.split() if w]
    if len(words) < 2:
        raise ValueError("Нужны минимум фамилия и имя")

    return {
        "fio": fio,
        "lastname": words[0],
        "firstname": words[1],
        "secondname": words[2] if len(words) > 2 else "",
        "birth_date": birth_date,
        "region": region,
    }


def _fssp_official_search(parsed: Dict[str, str], token: str) -> Dict[str, Any]:
    """Search FSSP via official task-based API.

    API docs: https://api-ip.fssprus.ru/
    """
    base_url = "https://api-ip.fssprus.ru/api/v1.0"
    params = {
        "token": token,
        "region": parsed["region"],
        "lastname": parsed["lastname"],
        "firstname": parsed["firstname"],
    }
    if parsed.get("secondname"):
        params["secondname"] = parsed["secondname"]

    birth = parsed.get("birth_date", "")
    if birth:
        # API usually expects DD.MM.YYYY; accept YYYY-MM-DD from user.
        if len(birth) == 10 and birth[4] == "-" and birth[7] == "-":
            y, m, d = birth.split("-")
            params["birthdate"] = f"{d}.{m}.{y}"
        else:
            params["birthdate"] = birth

    search_url = f"{base_url}/search/physical?{urlencode(params)}"
    search_resp = requests.get(search_url, timeout=15)
    if search_resp.status_code != 200:
        raise RuntimeError(f"FSSP API HTTP {search_resp.status_code}")

    search_data = search_resp.json()
    task_id = (search_data.get("response") or {}).get("task")
    if not task_id:
        return {"raw": search_data, "items": []}

    # Poll result endpoint
    result_params = {"token": token, "task": task_id}
    result_url = f"{base_url}/result?{urlencode(result_params)}"
    last_data: Dict[str, Any] = {}
    for _ in range(6):
        r = requests.get(result_url, timeout=15)
        if r.status_code != 200:
            raise RuntimeError(f"FSSP result HTTP {r.status_code}")
        last_data = r.json()
        status = (last_data.get("response") or {}).get("status")
        if status == 0:
            break
        time.sleep(2)

    result = (last_data.get("response") or {}).get("result") or []
    return {"raw": last_data, "items": result}


def _format_fssp_result(parsed: Dict[str, str], result: Dict[str, Any]) -> str:
    items = result.get("items") or []
    lines = [
        "✅ <b>Проверка ФССП (официальный источник)</b>",
        f"👤 ФИО: <code>{parsed.get('fio', '—')}</code>",
        f"🗺 Регион: <code>{parsed.get('region', '—')}</code>",
        "",
        f"Найдено производств: <b>{len(items)}</b>",
    ]

    for i, item in enumerate(items[:5], start=1):
        lines.append("")
        lines.append(f"<b>{i}) Производство</b>")
        lines.append(f"• Номер ИП: <code>{item.get('ip_num') or item.get('ipNumber') or '—'}</code>")
        lines.append(f"• Статус: {item.get('ip_exec_prist_name') or item.get('status') or '—'}")
        lines.append(f"• Сумма: {item.get('ip_sum') or item.get('sum') or '—'}")
        lines.append(f"• Отдел: {item.get('department') or item.get('depart_name') or '—'}")

    if not items:
        lines.append("По указанным данным записи не найдены или ещё обрабатываются.")

    lines.extend([
        "",
        "⚖️ Используйте данные только в законных целях и с соблюдением требований о персональных данных.",
    ])
    return _compact_lines(lines)


def _build_vk_photo_links(photo_url: str, query_hint: str) -> Dict[str, str]:
    """Build VK-focused links for photo lookup via search engines."""
    q = (query_hint or "").strip()

    links = {
        "vk_people": f"https://vk.com/search?c[section]=people&c[q]={quote(q)}" if q else "https://vk.com/search?c[section]=people",
        "vk_global": f"https://vk.com/feed?section=search&q={quote(q)}" if q else "https://vk.com/feed?section=search",
        "google_site_vk": "https://www.google.com/search?q=" + quote(f"site:vk.com {q}".strip()),
        "yandex_site_vk": "https://yandex.ru/search/?text=" + quote(f"site:vk.com {q}".strip()),
    }

    if photo_url:
        links["yandex_reverse_by_url"] = "https://yandex.com/images/search?rpt=imageview&url=" + quote(photo_url, safe="")

    return links


def _format_photo_result(photo_result: Dict[str, Any], vk_links: Dict[str, str]) -> str:
    metadata = _safe_get(photo_result, "results", "metadata", default={})
    engines = _safe_get(photo_result, "results", "image_search", default={})

    lines = [
        "✅ <b>Поиск по фото</b>",
        f"🖼 Файл: <code>{_safe_get(metadata, 'filename')}</code>",
        f"📐 Размер: {_safe_get(metadata, 'size')}",
        "",
        "<b>Интернет reverse image search</b>",
    ]

    if isinstance(engines, dict) and engines:
        shown = 0
        for engine_name in ["google", "yandex", "bing", "tineye", "saucenao", "iqdb"]:
            data = engines.get(engine_name)
            if not isinstance(data, dict):
                continue
            title = data.get("engine") or engine_name
            search_url = data.get("search_url") or ""
            upload_url = data.get("upload_url") or ""
            lines.append(f"• {title}: {search_url}")
            if upload_url:
                lines.append(f"  ↳ upload: {upload_url}")
            shown += 1
        if shown == 0:
            lines.append("• Не удалось получить список движков")
    else:
        lines.append("• Нет данных по reverse image search")

    lines.extend([
        "",
        "<b>Поиск во ВКонтакте</b>",
        f"• VK people: {vk_links.get('vk_people', '—')}",
        f"• VK search: {vk_links.get('vk_global', '—')}",
        f"• Google site:vk.com: {vk_links.get('google_site_vk', '—')}",
        f"• Yandex site:vk.com: {vk_links.get('yandex_site_vk', '—')}",
    ])

    if vk_links.get("yandex_reverse_by_url"):
        lines.append(f"• Yandex reverse по URL фото: {vk_links['yandex_reverse_by_url']}")

    lines.extend([
        "",
        "ℹ️ Для VK чаще всего лучше работают связки: reverse image search + `site:vk.com`.",
    ])
    return _compact_lines(lines)


def _enhance_photo_file(input_path: str, output_path: str) -> None:
    with Image.open(input_path) as img:
        img = ImageOps.exif_transpose(img)
        img = img.convert("RGB")
        img = ImageOps.autocontrast(img)
        img = ImageEnhance.Contrast(img).enhance(1.15)
        img = ImageEnhance.Color(img).enhance(1.05)
        img = img.filter(ImageFilter.UnsharpMask(radius=1.2, percent=150, threshold=3))
        img.save(output_path, format="JPEG", quality=92, optimize=True)


def _arg_from_context(context: ContextTypes.DEFAULT_TYPE) -> str:
    return " ".join(context.args).strip() if context.args else ""


def _normalize_tg_username(raw: str) -> str:
    value = (raw or "").strip()
    if not value:
        raise ValueError("Укажи Telegram-ник.")

    lowered = value.lower()
    prefixes = (
        "https://t.me/",
        "http://t.me/",
        "t.me/",
        "https://telegram.me/",
        "http://telegram.me/",
        "telegram.me/",
    )
    for prefix in prefixes:
        if lowered.startswith(prefix):
            value = value[len(prefix):]
            break

    value = value.split("?", 1)[0].split("/", 1)[0].strip()
    if value.startswith("@"):
        value = value[1:]

    if not _TG_USERNAME_RE.fullmatch(value):
        raise ValueError("Некорректный ник. Используй 5-32 символа: латиница, цифры, _.")

    return value


def _build_tg_nick_links(username: str) -> Dict[str, str]:
    query = f"site:t.me {username}"
    return {
        "profile": f"https://t.me/{quote(username)}",
        "tgstat": f"https://tgstat.com/search?query={quote(username)}",
        "google_site_tme": "https://www.google.com/search?q=" + quote(query),
        "yandex_site_tme": "https://yandex.ru/search/?text=" + quote(query),
        "bing_site_tme": "https://www.bing.com/search?q=" + quote(query),
        "duckduckgo_site_tme": "https://duckduckgo.com/?q=" + quote(query),
    }


def _lookup_breach_phones_by_username(username: str) -> List[Dict[str, str]]:
    """Find phone candidates for username from local breaches database."""
    candidates: List[Dict[str, str]] = []
    seen = set()

    for variant in (username, username.lower()):
        result = universal_search.data_breaches.search_by_username(variant)
        if not result.get("found"):
            continue
        for item in result.get("data", []):
            phone = str(item.get("phone") or "").strip()
            if not phone:
                continue
            key = (
                phone,
                str(item.get("username") or "").strip().lower(),
                str(item.get("platform") or "").strip().lower(),
            )
            if key in seen:
                continue
            seen.add(key)
            candidates.append(
                {
                    "phone": phone,
                    "username": str(item.get("username") or "").strip(),
                    "platform": str(item.get("platform") or "").strip(),
                }
            )

    return candidates[:10]


def _format_tg_nick_result(
    username: str, links: Dict[str, str], phone_candidates: List[Dict[str, str]]
) -> str:
    lines = [
        "✅ <b>Поиск по Telegram-нику</b>",
        f"👤 Ник: <code>@{username}</code>",
        "",
        "<b>Номера по нику (локальная БД утечек)</b>",
    ]

    if phone_candidates:
        lines.append(f"• Совпадений: <b>{len(phone_candidates)}</b>")
        for i, item in enumerate(phone_candidates[:5], start=1):
            platform = item.get("platform") or "—"
            found_username = item.get("username") or username
            lines.append(
                f"  {i}. <code>{item.get('phone', '—')}</code> | {platform} | <code>@{found_username}</code>"
            )
    else:
        lines.append("• Совпадений не найдено")

    lines.extend([
        "",
        "<b>Прямые ссылки</b>",
        f"• Профиль/канал: {links.get('profile', '—')}",
        f"• TGStat: {links.get('tgstat', '—')}",
        "",
        "<b>Поиск по вебу</b>",
        f"• Google: {links.get('google_site_tme', '—')}",
        f"• Yandex: {links.get('yandex_site_tme', '—')}",
        f"• Bing: {links.get('bing_site_tme', '—')}",
        f"• DuckDuckGo: {links.get('duckduckgo_site_tme', '—')}",
        "",
        "ℹ️ Если профиль приватный, чаще всего помогают внешние индексы и кэш.",
    ])
    return _compact_lines(lines)


def _format_tg_catalog_result(payload: Dict[str, Any]) -> str:
    items = payload.get("items", []) if isinstance(payload, dict) else []
    query = payload.get("query", "") if isinstance(payload, dict) else ""
    total = int(payload.get("total", 0) or 0) if isinstance(payload, dict) else 0

    lines = [
        "✅ <b>Чат/канал Telegram по базе</b>",
        f"🔎 Запрос: <code>{query}</code>",
        f"📊 Совпадений: <b>{total}</b>",
        "",
    ]

    if not items:
        lines.append("Ничего не найдено. Попробуй @ник, часть названия или ссылку t.me.")
        return _compact_lines(lines)

    for i, item in enumerate(items[:8], start=1):
        src = "Канал" if item.get("source_type") == "channel" else "Чат"
        title = item.get("title") or "—"
        link = item.get("link") or "—"
        members = item.get("members")
        members_txt = str(members) if members is not None else "—"
        username = item.get("username") or "—"

        lines.append(f"<b>{i}. {src}</b>")
        lines.append(f"• Название: {title}")
        lines.append(f"• Ссылка: {link}")
        lines.append(f"• Участники: {members_txt}")
        lines.append(f"• username: <code>@{username}</code>")

        if item.get("source_type") == "channel":
            lines.append(f"• Комментарии: {item.get('comments_mode') or '—'}")
        else:
            lines.append(f"• Можно писать: {item.get('can_write') or '—'}")
            lines.append(f"• Форум: {item.get('forum_mode') or '—'}")

        lines.append("")

    return _compact_lines(lines)


def _format_catalog_item(item: Dict[str, Any], i: int, title_prefix: str = "") -> List[str]:
    src = "Канал" if item.get("source_type") == "channel" else "Чат"
    title = item.get("title") or "—"
    link = item.get("link") or "—"
    members = item.get("members")
    members_txt = str(members) if members is not None else "—"
    username = item.get("username") or "—"

    lines = [f"<b>{i}. {title_prefix}{src}</b>"]
    lines.append(f"• Название: {title}")
    lines.append(f"• Ссылка: {link}")
    lines.append(f"• Участники: {members_txt}")
    lines.append(f"• username: <code>@{username}</code>")
    return lines


def _format_top_catalog_result(items: List[Dict[str, Any]], caption: str) -> str:
    lines = [f"✅ <b>{caption}</b>", ""]
    if not items:
        lines.append("Нет данных.")
        return _compact_lines(lines)

    for i, item in enumerate(items[:8], start=1):
        lines.extend(_format_catalog_item(item, i))
        lines.append("")
    return _compact_lines(lines)


def _format_random_catalog_result(item: Dict[str, Any]) -> str:
    lines = ["🎲 <b>Случайный чат/канал Telegram</b>", ""]
    if not item:
        lines.append("Каталог пуст.")
        return _compact_lines(lines)

    lines.extend(_format_catalog_item(item, 1))
    return _compact_lines(lines)


def _admin_panel_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Статус", callback_data="admin:status"),
                InlineKeyboardButton("Базы", callback_data="admin:db"),
            ],
            [
                InlineKeyboardButton("Топ каналы", callback_data="admin:top_channels"),
                InlineKeyboardButton("Топ чаты", callback_data="admin:top_chats"),
            ],
            [
                InlineKeyboardButton("Доступ к отчетам", callback_data="admin:report767_access"),
            ],
            [
                InlineKeyboardButton("Источники", callback_data="admin:sources"),
            ],
            [
                InlineKeyboardButton("Роли", callback_data="admin:roles"),
            ],
        ]
    )


def _admin_report767_access_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Добавить", callback_data="admin:report767_access_add"),
                InlineKeyboardButton("Удалить", callback_data="admin:report767_access_remove"),
            ],
            [
                InlineKeyboardButton("Список", callback_data="admin:report767_access_list"),
            ],
        ]
    )


def _admin_roles_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Добавить head", callback_data="admin:roles_add_head"),
                InlineKeyboardButton("Добавить team", callback_data="admin:roles_add_team"),
            ],
            [
                InlineKeyboardButton("Удалить", callback_data="admin:roles_remove"),
                InlineKeyboardButton("Список", callback_data="admin:roles_list"),
            ],
        ]
    )


def _admin_sources_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Добавить", callback_data="admin:sources_add"),
                InlineKeyboardButton("Удалить", callback_data="admin:sources_remove"),
            ],
            [
                InlineKeyboardButton("Список", callback_data="admin:sources_list"),
            ],
        ]
    )


def _sources_inline_markup(sources: List[Dict[str, Any]], max_items: int = 20) -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []
    for item in sources[:max_items]:
        label = f"{item.get('id')}. {item.get('name')}"
        rows.append([InlineKeyboardButton(label, callback_data=f"source:pick:{item.get('id')}")])
    return InlineKeyboardMarkup(rows)


def _count_sqlite_rows(db_path: str, table_name: str) -> int:
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute(f"SELECT COUNT(*) FROM {table_name}")
        value = int(cur.fetchone()[0])
        conn.close()
        return value
    except (sqlite3.Error, ValueError, TypeError):
        return 0


def _format_admin_status(bot_data: Dict[str, Any]) -> str:
    started_at_ts = float(bot_data.get("started_at_ts", 0.0) or 0.0)
    uptime_seconds = int(max(0.0, time.time() - started_at_ts)) if started_at_ts else 0
    allowed_chat_ids: Set[int] = bot_data.get("allowed_chat_ids", set())
    admin_chat_ids: Set[int] = bot_data.get("admin_chat_ids", set())

    lines = [
        "🛠 <b>Админ-панель: статус</b>",
        f"• PID: <code>{os.getpid()}</code>",
        f"• Время работы: <code>{uptime_seconds} сек</code>",
        f"• Разрешённых чатов: <b>{len(allowed_chat_ids)}</b>",
        f"• Админ-чатов: <b>{len(admin_chat_ids)}</b>",
    ]
    return _compact_lines(lines)


def _format_admin_db_stats() -> str:
    tg_stats = catalog_stats()
    breaches = _count_sqlite_rows("data_breaches.db", "users")
    directory = _count_sqlite_rows("business_directory.db", "records")
    report767_count = _count_sqlite_rows(REPORT_767_DB_PATH, "report767_entries")
    sources_count = _count_sqlite_rows(REPORT_767_DB_PATH, "source_items")
    orders_count = _count_sqlite_rows(REPORT_767_DB_PATH, "source_orders")
    lines = [
        "🛠 <b>Админ-панель: базы</b>",
        f"• Каталог Telegram (всего): <b>{tg_stats.get('total', 0)}</b>",
        f"• Каталог Telegram (каналы): <b>{tg_stats.get('channels', 0)}</b>",
        f"• Каталог Telegram (чаты): <b>{tg_stats.get('chats', 0)}</b>",
        f"• data_breaches users: <b>{breaches}</b>",
        f"• business_directory records: <b>{directory}</b>",
        f"• report767 entries: <b>{report767_count}</b>",
        f"• sources: <b>{sources_count}</b>",
        f"• green orders: <b>{orders_count}</b>",
    ]
    return _compact_lines(lines)


def _ensure_report767_table() -> None:
    conn = sqlite3.connect(REPORT_767_DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS report767_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                chat_id INTEGER,
                user_id INTEGER,
                username TEXT,
                author TEXT,
                team TEXT NOT NULL,
                reports_done INTEGER NOT NULL,
                reports_plan INTEGER NOT NULL,
                numbers_to_check INTEGER NOT NULL,
                positives INTEGER NOT NULL,
                active INTEGER NOT NULL,
                vbros INTEGER NOT NULL,
                predlog INTEGER NOT NULL,
                soglasiy INTEGER NOT NULL
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_report767_team_created ON report767_entries(team, created_at)"
        )
        # Lightweight migration for older tables.
        cur.execute("PRAGMA table_info(report767_entries)")
        existing_cols = {row[1] for row in cur.fetchall()}
        if "author" not in existing_cols:
            cur.execute("ALTER TABLE report767_entries ADD COLUMN author TEXT")
        if "numbers_to_check" not in existing_cols:
            cur.execute("ALTER TABLE report767_entries ADD COLUMN numbers_to_check INTEGER NOT NULL DEFAULT 0")
        conn.commit()
    finally:
        conn.close()


def _ensure_report767_access_table() -> None:
    conn = sqlite3.connect(REPORT_767_DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS report767_access (
                chat_id INTEGER PRIMARY KEY,
                added_at TEXT NOT NULL,
                added_by_chat INTEGER,
                added_by_user INTEGER,
                added_by_username TEXT
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def _ensure_roles_table() -> None:
    conn = sqlite3.connect(REPORT_767_DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS report767_roles (
                chat_id INTEGER PRIMARY KEY,
                role TEXT NOT NULL,
                added_at TEXT NOT NULL,
                added_by_chat INTEGER,
                added_by_user INTEGER,
                added_by_username TEXT
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def _ensure_sources_table() -> None:
    conn = sqlite3.connect(REPORT_767_DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS source_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                value TEXT NOT NULL,
                created_at TEXT NOT NULL,
                added_by_chat INTEGER,
                added_by_user INTEGER,
                added_by_username TEXT
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_source_items_name ON source_items(name)")
        conn.commit()
    finally:
        conn.close()


def _ensure_source_orders_table() -> None:
    conn = sqlite3.connect(REPORT_767_DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS source_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                chat_id INTEGER,
                user_id INTEGER,
                username TEXT,
                donor_link TEXT NOT NULL,
                full_name TEXT NOT NULL,
                birth_date TEXT NOT NULL,
                count INTEGER NOT NULL,
                vk_source TEXT NOT NULL
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def _parse_source_input(raw: str) -> Optional[Tuple[str, str]]:
    parts = [p.strip() for p in (raw or "").split("|", 1)]
    if len(parts) != 2:
        return None
    name, value = parts
    if not name or not value:
        return None
    return name, value


def _sources_add(name: str, value: str, update: Update) -> None:
    _ensure_sources_table()
    conn = sqlite3.connect(REPORT_767_DB_PATH)
    try:
        cur = conn.cursor()
        created_at = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
        added_by_chat = int(update.effective_chat.id) if update.effective_chat else None
        added_by_user = int(update.effective_user.id) if update.effective_user else None
        added_by_username = update.effective_user.username if update.effective_user else None
        cur.execute(
            """
            INSERT INTO source_items (name, value, created_at, added_by_chat, added_by_user, added_by_username)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (name, value, created_at, added_by_chat, added_by_user, added_by_username),
        )
        conn.commit()
    finally:
        conn.close()


def _sources_remove(source_id: int) -> int:
    _ensure_sources_table()
    conn = sqlite3.connect(REPORT_767_DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM source_items WHERE id = ?", (int(source_id),))
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def _sources_list(limit: int = 200) -> List[Dict[str, Any]]:
    _ensure_sources_table()
    conn = sqlite3.connect(REPORT_767_DB_PATH)
    try:
        cur = conn.cursor()
        rows = cur.execute(
            "SELECT id, name, value FROM source_items ORDER BY id DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
    finally:
        conn.close()

    return [{"id": row[0], "name": row[1], "value": row[2]} for row in rows]


def _get_source_by_id(source_id: int) -> Optional[Dict[str, Any]]:
    _ensure_sources_table()
    conn = sqlite3.connect(REPORT_767_DB_PATH)
    try:
        cur = conn.cursor()
        row = cur.execute(
            "SELECT id, name, value FROM source_items WHERE id = ?",
            (int(source_id),),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    return {"id": row[0], "name": row[1], "value": row[2]}


def _insert_green_order(entry: Dict[str, Any]) -> None:
    _ensure_source_orders_table()
    conn = sqlite3.connect(REPORT_767_DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO source_orders (
                created_at, chat_id, user_id, username,
                donor_link, full_name, birth_date, count, vk_source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry.get("created_at"),
                entry.get("chat_id"),
                entry.get("user_id"),
                entry.get("username"),
                entry.get("donor_link"),
                entry.get("full_name"),
                entry.get("birth_date"),
                int(entry.get("count", 0)),
                entry.get("vk_source"),
            ),
        )
        conn.commit()
    finally:
        conn.close()


async def _send_green_order_to_group(
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
) -> Tuple[bool, Optional[str]]:
    chat_id = context.application.bot_data.get("green_order_chat_id")
    if not chat_id:
        return False, "не настроено"
    thread_id = context.application.bot_data.get("green_order_thread_id")
    try:
        kwargs = {"chat_id": chat_id, "text": text}
        if thread_id:
            kwargs["message_thread_id"] = thread_id
        await context.bot.send_message(**kwargs)
        return True, None
    except Exception as exc:
        return False, str(exc)


def _roles_set(chat_id: int, role: str, update: Update) -> None:
    _ensure_roles_table()
    conn = sqlite3.connect(REPORT_767_DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT OR REPLACE INTO report767_roles (
                chat_id, role, added_at, added_by_chat, added_by_user, added_by_username
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                int(chat_id),
                role,
                datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
                int(update.effective_chat.id) if update.effective_chat else 0,
                int(update.effective_user.id) if update.effective_user else 0,
                (update.effective_user.username or "") if update.effective_user else "",
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _roles_remove(chat_id: int) -> int:
    _ensure_roles_table()
    conn = sqlite3.connect(REPORT_767_DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM report767_roles WHERE chat_id = ?", (int(chat_id),))
        conn.commit()
        return int(cur.rowcount or 0)
    finally:
        conn.close()


def _roles_list() -> List[Dict[str, Any]]:
    _ensure_roles_table()
    conn = sqlite3.connect(REPORT_767_DB_PATH)
    try:
        cur = conn.cursor()
        rows = cur.execute(
            "SELECT chat_id, role, added_at, added_by_username FROM report767_roles ORDER BY role, chat_id"
        ).fetchall()
    finally:
        conn.close()
    return [
        {
            "chat_id": int(row[0]),
            "role": str(row[1] or ""),
            "added_at": str(row[2] or ""),
            "added_by": str(row[3] or ""),
        }
        for row in rows
    ]


def _get_chat_role(chat_id: int) -> Optional[str]:
    _ensure_roles_table()
    conn = sqlite3.connect(REPORT_767_DB_PATH)
    try:
        cur = conn.cursor()
        row = cur.execute("SELECT role FROM report767_roles WHERE chat_id = ?", (int(chat_id),)).fetchone()
    finally:
        conn.close()
    return str(row[0]) if row and row[0] else None


def _report767_access_add(chat_id: int, update: Update) -> None:
    _ensure_report767_access_table()
    conn = sqlite3.connect(REPORT_767_DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT OR REPLACE INTO report767_access (
                chat_id, added_at, added_by_chat, added_by_user, added_by_username
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                int(chat_id),
                datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
                int(update.effective_chat.id) if update.effective_chat else 0,
                int(update.effective_user.id) if update.effective_user else 0,
                (update.effective_user.username or "") if update.effective_user else "",
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _report767_access_remove(chat_id: int) -> int:
    _ensure_report767_access_table()
    conn = sqlite3.connect(REPORT_767_DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM report767_access WHERE chat_id = ?", (int(chat_id),))
        conn.commit()
        return int(cur.rowcount or 0)
    finally:
        conn.close()


def _report767_access_list() -> List[int]:
    _ensure_report767_access_table()
    conn = sqlite3.connect(REPORT_767_DB_PATH)
    try:
        cur = conn.cursor()
        rows = cur.execute("SELECT chat_id FROM report767_access ORDER BY chat_id").fetchall()
    finally:
        conn.close()
    return [int(row[0]) for row in rows]


def _is_report767_stats_allowed(update: Update, bot_data: Dict[str, Any]) -> bool:
    admin_chat_ids: Set[int] = bot_data.get("admin_chat_ids", set())
    if _is_admin_chat(update, admin_chat_ids):
        return True
    if not update.effective_chat:
        return False
    chat_id = int(update.effective_chat.id)
    try:
        role = _get_chat_role(chat_id)
    except sqlite3.Error:
        role = None
    if role in {"head", "team"}:
        return True
    try:
        allowed = _report767_access_list()
    except sqlite3.Error:
        return False
    return chat_id in set(allowed)


def _get_gsheets_worksheet() -> Optional[Any]:
    global _GS_WORKSHEET, _GS_ERROR
    if _GS_WORKSHEET is not None or _GS_ERROR:
        return _GS_WORKSHEET

    if not _GSHEETS_AVAILABLE:
        _GS_ERROR = "gspread/google-auth not installed"
        return None

    creds_path = os.getenv("GOOGLE_SHEETS_CREDENTIALS_JSON", "").strip()
    creds_raw = os.getenv("GOOGLE_SHEETS_CREDENTIALS", "").strip()
    sheet_id = os.getenv("GOOGLE_SHEETS_ID", "").strip()
    sheet_tab = os.getenv("GOOGLE_SHEETS_TAB", "").strip()

    if not sheet_id:
        _GS_ERROR = "GOOGLE_SHEETS_ID not set"
        return None

    try:
        if creds_path:
            creds = Credentials.from_service_account_file(
                creds_path,
                scopes=["https://www.googleapis.com/auth/spreadsheets"],
            )
        elif creds_raw:
            creds = Credentials.from_service_account_info(
                json.loads(creds_raw),
                scopes=["https://www.googleapis.com/auth/spreadsheets"],
            )
        else:
            _GS_ERROR = "GOOGLE_SHEETS_CREDENTIALS_JSON or GOOGLE_SHEETS_CREDENTIALS not set"
            return None
    except Exception as exc:
        _GS_ERROR = f"credentials error: {exc}"
        return None

    try:
        client = gspread.authorize(creds)
        sh = client.open_by_key(sheet_id)
        worksheet = sh.worksheet(sheet_tab) if sheet_tab else sh.sheet1
        _GS_WORKSHEET = worksheet
        return worksheet
    except Exception as exc:
        _GS_ERROR = f"sheet open error: {exc}"
        return None


def _append_report767_to_gsheets(entry: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    ws = _get_gsheets_worksheet()
    if ws is None:
        return False, _GS_ERROR

    header = [
        "created_at",
        "chat_id",
        "user_id",
        "username",
        "author",
        "team",
        "numbers_to_check",
        "positives",
        "active",
        "vbros",
        "predlog",
        "soglasiy",
    ]
    row = [
        entry.get("created_at", ""),
        entry.get("chat_id", ""),
        entry.get("user_id", ""),
        entry.get("username", ""),
        entry.get("author", ""),
        entry.get("team", ""),
        entry.get("numbers_to_check", 0),
        entry.get("positives", 0),
        entry.get("active", 0),
        entry.get("vbros", 0),
        entry.get("predlog", 0),
        entry.get("soglasiy", 0),
    ]

    try:
        first_row = ws.row_values(1)
        if not first_row:
            ws.append_row(header, value_input_option="USER_ENTERED")
        ws.append_row(row, value_input_option="USER_ENTERED")
        return True, None
    except Exception as exc:
        return False, f"append error: {exc}"


def _parse_report767_single_number(raw: str) -> Optional[int]:
    values = [int(v) for v in re.findall(r"\d+", raw or "")]
    if len(values) != 1:
        return None
    return values[0]


def _insert_report767_entry(entry: Dict[str, Any]) -> None:
    _ensure_report767_table()
    conn = sqlite3.connect(REPORT_767_DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO report767_entries (
                created_at, chat_id, user_id, username, author, team, reports_done, reports_plan,
                numbers_to_check, positives, active, vbros, predlog, soglasiy
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry.get("created_at") or datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
                entry.get("chat_id"),
                entry.get("user_id"),
                entry.get("username"),
                entry.get("author"),
                entry["team"],
                int(entry.get("reports_done", 0)),
                int(entry.get("reports_plan", 0)),
                int(entry["numbers_to_check"]),
                int(entry["positives"]),
                int(entry["active"]),
                int(entry["vbros"]),
                int(entry["predlog"]),
                int(entry["soglasiy"]),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _get_report767_totals(team: Optional[str] = None) -> Dict[str, int]:
    _ensure_report767_table()
    conn = sqlite3.connect(REPORT_767_DB_PATH)
    try:
        cur = conn.cursor()
        query = (
            "SELECT COUNT(*), "
            "COALESCE(SUM(reports_done), 0), COALESCE(SUM(reports_plan), 0), "
            "COALESCE(SUM(numbers_to_check), 0), "
            "COALESCE(SUM(positives), 0), COALESCE(SUM(active), 0), "
            "COALESCE(SUM(vbros), 0), COALESCE(SUM(predlog), 0), COALESCE(SUM(soglasiy), 0) "
            "FROM report767_entries"
        )
        args: Tuple[Any, ...] = ()
        if team:
            query += " WHERE team = ?"
            args = (team,)
        row = cur.execute(query, args).fetchone() or (0, 0, 0, 0, 0, 0, 0, 0, 0)
    finally:
        conn.close()

    return {
        "entries": int(row[0] or 0),
        "reports_done": int(row[1] or 0),
        "reports_plan": int(row[2] or 0),
        "numbers_to_check": int(row[3] or 0),
        "positives": int(row[4] or 0),
        "active": int(row[5] or 0),
        "vbros": int(row[6] or 0),
        "predlog": int(row[7] or 0),
        "soglasiy": int(row[8] or 0),
    }


def _get_report767_team_rows() -> List[Dict[str, Any]]:
    _ensure_report767_table()
    conn = sqlite3.connect(REPORT_767_DB_PATH)
    try:
        cur = conn.cursor()
        rows = cur.execute(
            """
            SELECT
                team,
                COUNT(*) AS entries,
                COALESCE(SUM(reports_done), 0) AS reports_done,
                COALESCE(SUM(reports_plan), 0) AS reports_plan,
                COALESCE(SUM(numbers_to_check), 0) AS numbers_to_check,
                COALESCE(SUM(positives), 0) AS positives,
                COALESCE(SUM(active), 0) AS active,
                COALESCE(SUM(vbros), 0) AS vbros,
                COALESCE(SUM(predlog), 0) AS predlog,
                COALESCE(SUM(soglasiy), 0) AS soglasiy
            FROM report767_entries
            GROUP BY team
            ORDER BY team
            """
        ).fetchall()
    finally:
        conn.close()

    out: List[Dict[str, Any]] = []
    for row in rows:
        out.append(
            {
                "team": str(row[0] or ""),
                "entries": int(row[1] or 0),
                "reports_done": int(row[2] or 0),
                "reports_plan": int(row[3] or 0),
                "numbers_to_check": int(row[4] or 0),
                "positives": int(row[5] or 0),
                "active": int(row[6] or 0),
                "vbros": int(row[7] or 0),
                "predlog": int(row[8] or 0),
                "soglasiy": int(row[9] or 0),
            }
        )
    return out


def _format_report767_totals(title: str, totals: Dict[str, int]) -> List[str]:
    return [
        f"<b>{title}</b>",
        f"• Записей: <b>{totals.get('entries', 0)}</b>",
        f"• Номеров на проверку: <b>{totals.get('numbers_to_check', 0)}</b>",
        f"• Плюсовых: <b>{totals.get('positives', 0)}</b>",
        f"• Актив: <b>{totals.get('active', 0)}</b>",
        f"• Вброс: <b>{totals.get('vbros', 0)}</b>",
        f"• Предлог: <b>{totals.get('predlog', 0)}</b>",
        f"• Согласий: <b>{totals.get('soglasiy', 0)}</b>",
    ]


async def report767_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    allowed_chat_ids: Set[int] = context.application.bot_data.get("allowed_chat_ids", set())
    if await _deny_if_not_allowed(update, allowed_chat_ids):
        return
    if not update.message:
        return
    if not update.effective_user:
        await _reply_menu_text(update, "❌ Нужна авторизация через Telegram для отчёта 767.")
        return

    context.user_data["input_mode"] = MODE_REPORT_767_TEAM
    context.user_data["report767_draft"] = {}
    await _reply_menu_text(
        update,
        _ui_card(
            "Отчёт 767 · Шаг 1/7",
            [
                "Выбери тиму кнопкой ниже или отправь текстом.",
                "<code>kizaru1312</code>",
                "<code>apathy7</code>",
                "<code>stil1x315</code>",
            ],
            _back_hint(),
        ),
        reply_markup=_back_menu(),
    )
    await update.message.reply_text(
        "🧩 Доступные тимы:",
        reply_markup=_report767_team_inline(),
    )


async def report767_stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    allowed_chat_ids: Set[int] = context.application.bot_data.get("allowed_chat_ids", set())
    if await _deny_if_not_allowed(update, allowed_chat_ids):
        return
    if not update.message:
        return
    if not _is_report767_stats_allowed(update, context.application.bot_data):
        await _reply_menu_text(update, "⛔ Доступ к итогам 767 ограничен.")
        return

    try:
        team_rows = _get_report767_team_rows()
        grand = _get_report767_totals()
    except sqlite3.Error as exc:
        await _reply_menu_text(update, f"❌ Ошибка чтения таблицы 767: <code>{exc}</code>")
        return

    lines = ["📊 <b>Таблица 767 (подсчёт)</b>", ""]
    if not team_rows:
        lines.append("Пока нет записей.")
    else:
        for row in team_rows:
            lines.extend(_format_report767_totals(f"Тима: <code>{row.get('team', '—')}</code>", row))
            lines.append("")
    lines.extend(_format_report767_totals("Итого (все тимы)", grand))
    await _reply_menu_text(update, _compact_lines(lines))


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    allowed_chat_ids: Set[int] = context.application.bot_data.get("allowed_chat_ids", set())
    if await _deny_if_not_allowed(update, allowed_chat_ids):
        return

    if not update.message:
        return

    text = _ui_card(
        "Бот PhoneInfoga",
        [
            "OSINT-проверка телефонов, Telegram и фото в одном интерфейсе.",
            "Выбери нужную функцию кнопками ниже.",
            "Для перехода между режимами используй кнопки навигации.",
        ],
        _back_hint(),
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=_main_menu_for_update(update))


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    allowed_chat_ids: Set[int] = context.application.bot_data.get("allowed_chat_ids", set())
    if await _deny_if_not_allowed(update, allowed_chat_ids):
        return

    if not update.message:
        return

    await update.message.reply_text(
        _ui_card(
            "Справка по функциям",
            [
                "📞 Поиск номера — номер в международном формате.",
                "🖼 Поиск по фото — отправь фото для поиска.",
                "✨ Улучшение фото — отправь фото для обработки.",
                "👤 Ник Telegram — введи <code>@ник</code>.",
                "💬 Каталог Telegram — ник, ссылка или часть названия.",
                "⚖️ Проверка ФССП — формат: ФИО;дата;регион.",
                "📊 Отчёт 767 — пошаговое заполнение отчёта.",
                "📦 Источники — выдача/управление источниками.",
                "🟢 Заказ у зелёных — форма заказа по шаблону.",
                "🆔 Мой ID — chat_id, user_id, username.",
                "🛠 Панель администратора — управление доступами и ролями.",
                "Можно отправить номер или <code>@ник</code> отдельным сообщением.",
            ],
            "Используй кнопки меню для быстрого перехода.",
        ),
        parse_mode=ParseMode.HTML,
        reply_markup=_main_menu_for_update(update),
    )


async def id_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    allowed_chat_ids: Set[int] = context.application.bot_data.get("allowed_chat_ids", set())
    if await _deny_if_not_allowed(update, allowed_chat_ids):
        return
    if not update.message:
        return

    chat_id = update.effective_chat.id if update.effective_chat else "—"
    user_id = update.effective_user.id if update.effective_user else "—"
    username = update.effective_user.username if update.effective_user else ""
    username = f"@{username}" if username else "—"

    await _reply_menu_text(
        update,
        f"🆔 <b>IDs</b>\n• chat_id: <code>{chat_id}</code>\n• user_id: <code>{user_id}</code>\n• username: <code>{username}</code>",
    )


async def uptime_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    allowed_chat_ids: Set[int] = context.application.bot_data.get("allowed_chat_ids", set())
    if await _deny_if_not_allowed(update, allowed_chat_ids):
        return
    if not update.message:
        return

    started_at = context.application.bot_data.get("started_at_ts")
    if not started_at:
        await _reply_menu_text(update, "⏱ Аптайм недоступен.")
        return

    uptime_seconds = int(time.time() - float(started_at))
    days, rem = divmod(uptime_seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, seconds = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days}д")
    if hours:
        parts.append(f"{hours}ч")
    if minutes:
        parts.append(f"{minutes}м")
    parts.append(f"{seconds}с")
    uptime_str = " ".join(parts)

    await _reply_menu_text(update, f"⏱ Аптайм: <b>{uptime_str}</b>")


async def _run_search_and_reply(update: Update, phone: str) -> None:
    if not update.message:
        return

    await update.message.reply_text("⏳ Выполняю поиск по номеру...")
    payload = universal_search.universal_phone_search(
        phone,
        ["basic", "owner", "data_breaches", "ru_resources", "search_engines", "social"],
    )
    if not payload.get("valid"):
        err = payload.get("error", "Не удалось обработать номер")
        await _reply_menu_text(update, f"❌ {err}")
        return

    result_text = _format_result(payload)
    await _reply_with_pdf_report(update, f"Отчет по номеру {phone}", result_text, include_text=True)


async def search_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    allowed_chat_ids: Set[int] = context.application.bot_data.get("allowed_chat_ids", set())
    if await _deny_if_not_allowed(update, allowed_chat_ids):
        return

    if not update.message:
        return

    if not context.args:
        await _reply_menu_text(
            update,
            _ui_card(
                "Поиск номера",
                ["Введи номер в формате E.164.", "Пример: <code>+79001234567</code>"],
            ),
        )
        return

    phone = _arg_from_context(context)
    await _run_search_and_reply(update, phone)


async def ip_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    allowed_chat_ids: Set[int] = context.application.bot_data.get("allowed_chat_ids", set())
    if await _deny_if_not_allowed(update, allowed_chat_ids):
        return

    if not update.message:
        return

    value = _arg_from_context(context)
    if not value:
        await _reply_menu_text(
            update,
            _ui_card(
                "Проверка IP",
                ["Укажи IP-адрес для анализа.", "Пример: <code>8.8.8.8</code>"],
            ),
        )
        return

    await update.message.reply_text("⏳ Выполняю проверку IP...")
    payload = universal_search.xosint.ip_lookup(value)
    if payload.get("valid") is False:
        await _reply_menu_text(update, _format_ip_result(payload))
        return

    result_text = _format_ip_result(payload)
    await _reply_with_pdf_report(update, f"IP отчет {value}", result_text, include_text=True)


async def email_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    allowed_chat_ids: Set[int] = context.application.bot_data.get("allowed_chat_ids", set())
    if await _deny_if_not_allowed(update, allowed_chat_ids):
        return

    if not update.message:
        return

    value = _arg_from_context(context)
    if not value:
        await _reply_menu_text(
            update,
            _ui_card(
                "Проверка Email",
                ["Укажи email для проверки.", "Пример: <code>test@example.com</code>"],
            ),
        )
        return

    await update.message.reply_text("⏳ Выполняю проверку email...")
    payload = universal_search.xosint.email_check(value)
    if payload.get("valid") is False:
        await _reply_menu_text(update, _format_email_result(payload))
        return

    result_text = _format_email_result(payload)
    await _reply_with_pdf_report(update, f"Email отчет {value}", result_text, include_text=True)


async def _run_tg_search_and_reply(update: Update, raw_value: str) -> None:
    if not update.message:
        return

    try:
        username = _normalize_tg_username(raw_value)
    except ValueError as exc:
        await _reply_menu_text(update, f"❌ {exc}")
        return

    await update.message.reply_text("⏳ Ищу следы по нику...")
    links = _build_tg_nick_links(username)
    phone_candidates = _lookup_breach_phones_by_username(username)
    result_text = _format_tg_nick_result(username, links, phone_candidates)
    await _reply_with_pdf_report(update, f"Отчет по Telegram нику @{username}", result_text, include_text=True)


async def tg_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    allowed_chat_ids: Set[int] = context.application.bot_data.get("allowed_chat_ids", set())
    if await _deny_if_not_allowed(update, allowed_chat_ids):
        return

    if not update.message:
        return

    value = _arg_from_context(context)
    if not value:
        await _reply_menu_text(
            update,
            _ui_card(
                "Поиск Telegram-ника",
                ["Укажи ник пользователя.", "Пример: <code>@nickname</code>"],
            ),
        )
        return

    await _run_tg_search_and_reply(update, value)


async def _run_tg_catalog_search_and_reply(update: Update, query: str) -> None:
    if not update.message:
        return

    text = (query or "").strip()
    if not text:
        await _reply_menu_text(
            update,
            _ui_card(
                "Каталог Telegram",
                [
                    "Укажи ник, ссылку или часть названия.",
                    "Пример: <code>@nickname</code> или <code>t.me/example</code>",
                ],
            ),
        )
        return

    source_type = "all"
    lowered = text.lower()
    if lowered.startswith("chat "):
        source_type = "chat"
        text = text[5:].strip()
    elif lowered.startswith("channel "):
        source_type = "channel"
        text = text[8:].strip()
    elif lowered.startswith("чат "):
        source_type = "chat"
        text = text[4:].strip()
    elif lowered.startswith("канал "):
        source_type = "channel"
        text = text[6:].strip()

    if not text:
        await _reply_menu_text(
            update,
            _ui_card(
                "Каталог Telegram",
                [
                    "После фильтра нужен текст запроса.",
                    "Пример: <code>chat @nickname</code>",
                ],
            ),
        )
        return

    await update.message.reply_text("⏳ Ищу в базе чатов и каналов Telegram...")
    payload = search_catalog(text, source_type=source_type, limit=8, offset=0)
    if not payload.get("items") and int(payload.get("total", 0) or 0) == 0:
        await _reply_menu_text(update, _format_tg_catalog_result(payload))
        return

    result_text = _format_tg_catalog_result(payload)
    await _reply_with_pdf_report(update, f"Каталог Telegram: {text}", result_text, include_text=True)


async def tg_catalog_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    allowed_chat_ids: Set[int] = context.application.bot_data.get("allowed_chat_ids", set())
    if await _deny_if_not_allowed(update, allowed_chat_ids):
        return

    if not update.message:
        return

    value = _arg_from_context(context)
    if not value:
        await _reply_menu_text(
            update,
            _ui_card(
                "Каталог Telegram",
                [
                    "Укажи ник, ссылку или часть названия.",
                    "Пример: <code>@nickname</code> или <code>t.me/example</code>",
                ],
            ),
        )
        return

    await _run_tg_catalog_search_and_reply(update, value)


async def top_channels_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    allowed_chat_ids: Set[int] = context.application.bot_data.get("allowed_chat_ids", set())
    if await _deny_if_not_allowed(update, allowed_chat_ids):
        return
    if not update.message:
        return
    items = top_catalog(source_type="channel", limit=8)
    result_text = _format_top_catalog_result(items, "Топ каналов Telegram")
    await _reply_with_pdf_report(update, "Топ каналов Telegram", result_text, include_text=True)


async def top_chats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    allowed_chat_ids: Set[int] = context.application.bot_data.get("allowed_chat_ids", set())
    if await _deny_if_not_allowed(update, allowed_chat_ids):
        return
    if not update.message:
        return
    items = top_catalog(source_type="chat", limit=8)
    result_text = _format_top_catalog_result(items, "Топ чатов Telegram")
    await _reply_with_pdf_report(update, "Топ чатов Telegram", result_text, include_text=True)


async def random_tg_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    allowed_chat_ids: Set[int] = context.application.bot_data.get("allowed_chat_ids", set())
    if await _deny_if_not_allowed(update, allowed_chat_ids):
        return
    if not update.message:
        return
    item = random_catalog(source_type="all")
    result_text = _format_random_catalog_result(item or {})
    await _reply_with_pdf_report(update, "Случайный чат/канал Telegram", result_text, include_text=True)


async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    admin_chat_ids: Set[int] = context.application.bot_data.get("admin_chat_ids", set())
    if not _is_admin_chat(update, admin_chat_ids):
        if update.message:
            await update.message.reply_text("⛔ Доступ к админке запрещен.")
        return
    if not update.message:
        return
    await update.message.reply_text(
        _ui_card(
            "Админ-панель",
            ["Выбери действие из кнопок ниже."],
            _back_hint(),
        ),
        parse_mode=ParseMode.HTML,
        reply_markup=_admin_panel_markup(),
    )


async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return

    admin_chat_ids: Set[int] = context.application.bot_data.get("admin_chat_ids", set())
    if not _is_admin_chat(update, admin_chat_ids):
        await query.answer("Нет доступа", show_alert=True)
        return

    data = query.data or ""
    await query.answer()

    if data == "admin:status":
        await query.message.reply_text(
            _format_admin_status(context.application.bot_data),
            parse_mode=ParseMode.HTML,
        )
        return

    if data == "admin:db":
        await query.message.reply_text(
            _format_admin_db_stats(),
            parse_mode=ParseMode.HTML,
        )
        return

    if data == "admin:top_channels":
        items = top_catalog(source_type="channel", limit=8)
        await query.message.reply_text(
            _format_top_catalog_result(items, "Топ каналов Telegram"),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        return

    if data == "admin:top_chats":
        items = top_catalog(source_type="chat", limit=8)
        await query.message.reply_text(
            _format_top_catalog_result(items, "Топ чатов Telegram"),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        return

    if data == "admin:report767_access":
        await query.message.reply_text(
            "Управление доступом к итогам отчётов 767:",
            reply_markup=_admin_report767_access_markup(),
        )
        return

    if data == "admin:report767_access_add":
        context.user_data["input_mode"] = MODE_REPORT_767_ACCESS_ADD
        await query.message.reply_text(
            "Введи <b>chat_id</b>, которому выдать доступ к итогам 767.",
            parse_mode=ParseMode.HTML,
            reply_markup=_back_menu(),
        )
        return

    if data == "admin:report767_access_remove":
        context.user_data["input_mode"] = MODE_REPORT_767_ACCESS_REMOVE
        await query.message.reply_text(
            "Введи <b>chat_id</b>, у которого нужно снять доступ к итогам 767.",
            parse_mode=ParseMode.HTML,
            reply_markup=_back_menu(),
        )
        return

    if data == "admin:report767_access_list":
        try:
            items = _report767_access_list()
        except sqlite3.Error as exc:
            await query.message.reply_text(
                f"❌ Ошибка чтения доступа 767: <code>{exc}</code>",
                parse_mode=ParseMode.HTML,
                reply_markup=_main_menu_for_update(update),
            )
            return

        if not items:
            await query.message.reply_text("Список доступа пуст.", reply_markup=_main_menu_for_update(update))
            return

        lines = ["<b>Доступ к итогам 767</b>"]
        for chat_id in items:
            lines.append(f"• <code>{chat_id}</code>")
        await query.message.reply_text(
            _compact_lines(lines),
            parse_mode=ParseMode.HTML,
            reply_markup=_main_menu_for_update(update),
        )
        return

    if data == "admin:sources":
        await query.message.reply_text(
            "Управление источниками:",
            reply_markup=_admin_sources_markup(),
        )
        return

    if data == "admin:sources_add":
        context.user_data["input_mode"] = MODE_SOURCE_ADD
        await query.message.reply_text(
            "Добавление источника.\nФормат: <code>Название | Ссылка/описание</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=_back_menu(),
        )
        return

    if data == "admin:sources_remove":
        context.user_data["input_mode"] = MODE_SOURCE_REMOVE
        await query.message.reply_text(
            "Удаление источника.\nУкажи ID источника (из списка).",
            reply_markup=_back_menu(),
        )
        return

    if data == "admin:sources_list":
        try:
            items = _sources_list()
        except sqlite3.Error as exc:
            await query.message.reply_text(
                f"❌ Ошибка чтения источников: <code>{exc}</code>",
                parse_mode=ParseMode.HTML,
                reply_markup=_main_menu_for_update(update),
            )
            return

        if not items:
            await query.message.reply_text("Список источников пуст.", reply_markup=_main_menu_for_update(update))
            return

        lines = ["<b>Источники</b>"]
        for item in items[:50]:
            value = item.get("value") or ""
            if len(value) > 60:
                value = value[:57] + "..."
            lines.append(f"• <code>{item.get('id')}</code> — {item.get('name')} — {value}")
        await query.message.reply_text(
            _compact_lines(lines),
            parse_mode=ParseMode.HTML,
            reply_markup=_main_menu_for_update(update),
        )
        return

    if data == "admin:roles":
        await query.message.reply_text(
            "Управление ролями (head/team):",
            reply_markup=_admin_roles_markup(),
        )
        return

    if data == "admin:roles_add_head":
        context.user_data["input_mode"] = MODE_ADMIN_ROLE_ADD_HEAD
        await query.message.reply_text(
            "Введи <b>chat_id</b> для роли <code>head</code>.",
            parse_mode=ParseMode.HTML,
            reply_markup=_back_menu(),
        )
        return

    if data == "admin:roles_add_team":
        context.user_data["input_mode"] = MODE_ADMIN_ROLE_ADD_TEAM
        await query.message.reply_text(
            "Введи <b>chat_id</b> для роли <code>team</code>.",
            parse_mode=ParseMode.HTML,
            reply_markup=_back_menu(),
        )
        return

    if data == "admin:roles_remove":
        context.user_data["input_mode"] = MODE_ADMIN_ROLE_REMOVE
        await query.message.reply_text(
            "Введи <b>chat_id</b>, чтобы удалить роль.",
            parse_mode=ParseMode.HTML,
            reply_markup=_back_menu(),
        )
        return

    if data == "admin:roles_list":
        try:
            items = _roles_list()
        except sqlite3.Error as exc:
            await query.message.reply_text(
                f"❌ Ошибка чтения ролей: <code>{exc}</code>",
                parse_mode=ParseMode.HTML,
                reply_markup=_main_menu_for_update(update),
            )
            return

        if not items:
            await query.message.reply_text("Список ролей пуст.", reply_markup=_main_menu_for_update(update))
            return

        lines = ["<b>Роли</b>"]
        for item in items:
            added_by = f" @{item.get('added_by')}" if item.get("added_by") else ""
            lines.append(f"• <code>{item.get('chat_id')}</code> — <b>{item.get('role')}</b>{added_by}")
        await query.message.reply_text(
            _compact_lines(lines),
            parse_mode=ParseMode.HTML,
            reply_markup=_main_menu_for_update(update),
        )
        return


async def report767_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    allowed_chat_ids: Set[int] = context.application.bot_data.get("allowed_chat_ids", set())
    if await _deny_if_not_allowed(update, allowed_chat_ids):
        if update.callback_query:
            await update.callback_query.answer()
        return

    query = update.callback_query
    if not query:
        return
    data = query.data or ""
    await query.answer()

    if data.startswith("report767:team:"):
        team = data.split("report767:team:", 1)[-1].strip().lower()
        if team not in REPORT_767_TEAMS:
            await query.message.reply_text(
                "❌ Некорректная тима. Используй кнопки или отправь название текстом.",
                reply_markup=_back_menu(),
            )
            return

        draft = context.user_data.get("report767_draft")
        if not isinstance(draft, dict):
            draft = {}
        draft["team"] = team
        context.user_data["report767_draft"] = draft
        context.user_data["input_mode"] = MODE_REPORT_767_NUMBERS_TO_CHECK

        with contextlib.suppress(Exception):
            await query.message.edit_reply_markup(reply_markup=None)

        await query.message.reply_text(
            f"Тима выбрана: <code>{team}</code>\n"
            "Шаг 2/7: введи <b>номеров на проверку</b> (одно число).",
            parse_mode=ParseMode.HTML,
            reply_markup=_back_menu(),
        )
        return


async def source_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    allowed_chat_ids: Set[int] = context.application.bot_data.get("allowed_chat_ids", set())
    if await _deny_if_not_allowed(update, allowed_chat_ids):
        if update.callback_query:
            await update.callback_query.answer()
        return

    query = update.callback_query
    if not query:
        return
    data = query.data or ""
    await query.answer()

    if data.startswith("source:pick:"):
        context.user_data.pop("input_mode", None)
        try:
            source_id = int(data.split("source:pick:", 1)[-1])
        except (TypeError, ValueError):
            await query.message.reply_text("❌ Некорректный источник.", reply_markup=_main_menu_for_update(update))
            return

        item = _get_source_by_id(source_id)
        if not item:
            await query.message.reply_text("❌ Источник не найден.", reply_markup=_main_menu_for_update(update))
            return

        await query.message.reply_text(
            f"Источник: <b>{item.get('name')}</b>\n{item.get('value')}",
            parse_mode=ParseMode.HTML,
            reply_markup=_main_menu_for_update(update),
        )
        return
async def fssp_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    allowed_chat_ids: Set[int] = context.application.bot_data.get("allowed_chat_ids", set())
    if await _deny_if_not_allowed(update, allowed_chat_ids):
        return

    if not update.message:
        return

    value = _arg_from_context(context)
    if not value:
        await _reply_menu_text(
            update,
            "Формат: <code>/fssp Иванов Иван Иванович;1990-01-01;77</code>\n"
            "Где: ФИО;дата рождения (опц.);код региона (опц.).",
        )
        return

    token = os.getenv("FSSP_API_TOKEN", "").strip()
    if not token:
        await _reply_menu_text(
            update,
            "⚠️ Не задан <code>FSSP_API_TOKEN</code> в .env.\n"
            "Пока можно проверить вручную на официальном сервисе: https://fssp.gov.ru/iss/ip",
        )
        return

    try:
        parsed = _parse_fssp_input(value)
    except ValueError as exc:
        await _reply_menu_text(update, f"❌ {exc}")
        return

    await update.message.reply_text("⏳ Проверяю ФССП по официальному API...")
    try:
        result = _fssp_official_search(parsed, token)
        result_text = _format_fssp_result(parsed, result)
        await _reply_with_pdf_report(update, f"Отчет ФССП {parsed.get('fio', '')}", result_text, include_text=True)
    except (requests.RequestException, RuntimeError, ValueError) as exc:
        await _reply_menu_text(
            update,
            "❌ Ошибка запроса ФССП API.\n"
            f"Детали: <code>{str(exc)}</code>\n"
            "Проверьте токен/формат данных или используйте https://fssp.gov.ru/iss/ip",
        )


async def photo_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    allowed_chat_ids: Set[int] = context.application.bot_data.get("allowed_chat_ids", set())
    if await _deny_if_not_allowed(update, allowed_chat_ids):
        return

    if not update.message or not update.message.photo:
        return

    mode = str(context.user_data.get("input_mode", ""))
    if mode == MODE_PHOTO_ENHANCE:
        context.user_data.pop("input_mode", None)
        await update.message.reply_text("⏳ Улучшаю фото...", reply_markup=_main_menu_for_update(update))

        photo = update.message.photo[-1]
        tg_file = await context.bot.get_file(photo.file_id)

        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp_in:
            tmp_in_path = tmp_in.name
        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp_out:
            tmp_out_path = tmp_out.name

        try:
            await tg_file.download_to_drive(custom_path=tmp_in_path)
            _enhance_photo_file(tmp_in_path, tmp_out_path)
            with open(tmp_out_path, "rb") as fh:
                await update.message.reply_photo(
                    fh,
                    caption="✅ Улучшенная версия",
                    reply_markup=_main_menu_for_update(update),
                )
        except (OSError, ValueError, RuntimeError) as exc:
            await _reply_menu_text(update, f"❌ Ошибка улучшения фото: <code>{str(exc)}</code>")
        finally:
            for path in (tmp_in_path, tmp_out_path):
                try:
                    os.remove(path)
                except OSError:
                    pass
        return

    if mode == MODE_PHOTO_SEARCH:
        context.user_data.pop("input_mode", None)

    await update.message.reply_text("⏳ Анализирую фото и готовлю ссылки для интернета и VK...", reply_markup=_main_menu_for_update(update))

    # Highest resolution photo from Telegram message.
    photo = update.message.photo[-1]
    tg_file = await context.bot.get_file(photo.file_id)

    with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
        tmp_path = tmp.name

    try:
        await tg_file.download_to_drive(custom_path=tmp_path)
        photo_result = universal_search.universal_photo_search(tmp_path, ["metadata", "search_engines"])

        token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        file_url = ""
        if token and getattr(tg_file, "file_path", ""):
            file_url = f"https://api.telegram.org/file/bot{token}/{tg_file.file_path}"

        query_hint = update.message.caption or _safe_get(photo_result, "results", "metadata", "filename", default="")
        vk_links = _build_vk_photo_links(file_url, str(query_hint))

        result_text = _format_photo_result(photo_result, vk_links)
        await _reply_with_pdf_report(update, "Отчет по фото", result_text, include_text=True)
    except (requests.RequestException, OSError, ValueError, RuntimeError) as exc:
        await _reply_menu_text(update, f"❌ Ошибка анализа фото: <code>{str(exc)}</code>")
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


async def unknown_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    allowed_chat_ids: Set[int] = context.application.bot_data.get("allowed_chat_ids", set())
    if await _deny_if_not_allowed(update, allowed_chat_ids):
        return
    if not update.message:
        return
    await _reply_menu_text(
        update,
        _ui_card(
            "Команда не распознана",
            ["Используй кнопки главного меню для выбора функции."],
        ),
    )


async def text_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    allowed_chat_ids: Set[int] = context.application.bot_data.get("allowed_chat_ids", set())
    if await _deny_if_not_allowed(update, allowed_chat_ids):
        return

    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()
    mode = str(context.user_data.get("input_mode", ""))

    if text == BTN_BACK:
        _clear_input_state(context)
        await update.message.reply_text(
            _ui_card("Главное меню", ["Выбери нужную функцию из списка ниже."]),
            parse_mode=ParseMode.HTML,
            reply_markup=_main_menu_for_update(update),
        )
        return

    if text == BTN_HOME:
        _clear_input_state(context)
        await update.message.reply_text(
            _ui_card("Главное меню", ["Выбери нужную функцию из списка ниже."]),
            parse_mode=ParseMode.HTML,
            reply_markup=_main_menu_for_update(update),
        )
        return

    # UI keyboard button actions
    if text == BTN_PHONE:
        _clear_input_state(context)
        await update.message.reply_text(
            _ui_card(
                "Поиск номера",
                [
                    "Введи номер в международном формате.",
                    "Пример: <code>+79001234567</code>",
                ],
                _back_hint(),
            ),
            parse_mode=ParseMode.HTML,
            reply_markup=_back_menu(),
        )
        return

    if text == BTN_PHOTO:
        context.user_data["input_mode"] = MODE_PHOTO_SEARCH
        await update.message.reply_text(
            _ui_card(
                "Поиск по фото",
                ["Пришли фото, и я соберу ссылки reverse image search (включая VK)."],
                _back_hint(),
            ),
            parse_mode=ParseMode.HTML,
            reply_markup=_back_menu(),
        )
        return

    if text == BTN_PHOTO_ENHANCE:
        context.user_data["input_mode"] = MODE_PHOTO_ENHANCE
        await update.message.reply_text(
            _ui_card(
                "Улучшение фото",
                ["Пришли фото, я обработаю его и отправлю улучшенную версию."],
                _back_hint(),
            ),
            parse_mode=ParseMode.HTML,
            reply_markup=_back_menu(),
        )
        return

    if text == BTN_FSSP:
        _clear_input_state(context)
        await update.message.reply_text(
            _ui_card(
                "Проверка ФССП",
                ["Формат ввода: <code>Иванов Иван Иванович;1990-01-01;77</code>"],
                _back_hint(),
            ),
            parse_mode=ParseMode.HTML,
            reply_markup=_back_menu(),
        )
        return

    if text == BTN_REPORT_767:
        _clear_input_state(context)
        await report767_cmd(update, context)
        return

    if text == BTN_SOURCE:
        context.user_data["input_mode"] = MODE_SOURCE_PICK
        try:
            items = _sources_list()
        except sqlite3.Error as exc:
            await _reply_menu_text(update, f"❌ Ошибка чтения источников: <code>{exc}</code>")
            return

        if not items:
            await _reply_menu_text(
                update,
                _ui_card("Источник", ["Список источников пуст. Обратись к администратору."]),
            )
            return

        await update.message.reply_text(
            _ui_card("Источник", ["Выбери источник из списка ниже."], _back_hint()),
            parse_mode=ParseMode.HTML,
            reply_markup=_back_menu(),
        )
        await update.message.reply_text(
            "📚 Доступные источники:",
            reply_markup=_sources_inline_markup(items),
        )
        return

    if text == BTN_GREEN_ORDER:
        context.user_data["input_mode"] = MODE_GREEN_ORDER_DONOR
        context.user_data["green_order"] = {}
        await update.message.reply_text(
            _ui_card(
                "Заказ у зелёных · Шаг 1/5",
                ["Ссылка на донора (Instagram/Telegram-канал)."],
                _back_hint(),
            ),
            parse_mode=ParseMode.HTML,
            reply_markup=_back_menu(),
        )
        return

    if text == BTN_TG:
        _clear_input_state(context)
        await update.message.reply_text(
            _ui_card(
                "Поиск Telegram-ника",
                ["Введи ник пользователя.", "Пример: <code>@nickname</code>"],
                _back_hint(),
            ),
            parse_mode=ParseMode.HTML,
            reply_markup=_back_menu(),
        )
        return

    if text == BTN_TG_CATALOG:
        context.user_data["input_mode"] = "tg_catalog"
        await update.message.reply_text(
            _ui_card(
                "Каталог Telegram",
                ["Введи @ник, часть названия или ссылку t.me."],
                _back_hint(),
            ),
            parse_mode=ParseMode.HTML,
            reply_markup=_back_menu(),
        )
        return

    if text == BTN_HELP:
        _clear_input_state(context)
        await help_cmd(update, context)
        return

    if text == BTN_ADMIN:
        _clear_input_state(context)
        await admin_cmd(update, context)
        return

    if text == BTN_ID:
        _clear_input_state(context)
        await id_cmd(update, context)
        return

    if mode == MODE_SOURCE_PICK:
        parsed = _parse_report767_single_number(text)
        if parsed is None:
            try:
                items = _sources_list()
            except sqlite3.Error as exc:
                await _reply_menu_text(update, f"❌ Ошибка чтения источников: <code>{exc}</code>")
                return
            await update.message.reply_text(
                _ui_card("Источник", ["Нужен ID источника из списка ниже."], _back_hint()),
                parse_mode=ParseMode.HTML,
                reply_markup=_sources_inline_markup(items),
            )
            return
        item = _get_source_by_id(int(parsed))
        context.user_data.pop("input_mode", None)
        if not item:
            await _reply_menu_text(update, _ui_card("Источник", ["❌ Источник не найден."]))
            return
        await _reply_menu_text(
            update,
            _ui_card(
                f"Источник: {item.get('name')}",
                [str(item.get("value", "—"))],
            ),
        )
        return

    if mode == MODE_SOURCE_ADD:
        admin_chat_ids: Set[int] = context.application.bot_data.get("admin_chat_ids", set())
        if not _is_admin_chat(update, admin_chat_ids):
            context.user_data.pop("input_mode", None)
            await _reply_menu_text(update, "⛔ Доступ к админке запрещен.")
            return
        parsed = _parse_source_input(text)
        if parsed is None:
            await update.message.reply_text(
                _ui_card(
                    "Добавление источника",
                    ["Формат: <code>Название | Ссылка/описание</code>"],
                    _back_hint(),
                ),
                parse_mode=ParseMode.HTML,
                reply_markup=_back_menu(),
            )
            return
        name, value = parsed
        try:
            _sources_add(name, value, update)
        except sqlite3.Error as exc:
            context.user_data.pop("input_mode", None)
            await _reply_menu_text(update, f"❌ Ошибка добавления источника: <code>{exc}</code>")
            return
        context.user_data.pop("input_mode", None)
        await _reply_menu_text(update, _ui_card("Источник", [f"✅ Добавлен: <b>{name}</b>"]))
        return

    if mode == MODE_SOURCE_REMOVE:
        admin_chat_ids: Set[int] = context.application.bot_data.get("admin_chat_ids", set())
        if not _is_admin_chat(update, admin_chat_ids):
            context.user_data.pop("input_mode", None)
            await _reply_menu_text(update, "⛔ Доступ к админке запрещен.")
            return
        parsed = _parse_report767_single_number(text)
        if parsed is None:
            await update.message.reply_text(
                _ui_card(
                    "Удаление источника",
                    ["Нужен ID источника (число)."],
                    _back_hint(),
                ),
                parse_mode=ParseMode.HTML,
                reply_markup=_back_menu(),
            )
            return
        try:
            removed = _sources_remove(int(parsed))
        except sqlite3.Error as exc:
            context.user_data.pop("input_mode", None)
            await _reply_menu_text(update, f"❌ Ошибка удаления источника: <code>{exc}</code>")
            return
        context.user_data.pop("input_mode", None)
        if removed:
            await _reply_menu_text(update, _ui_card("Источник", [f"✅ Удалён ID: <code>{parsed}</code>"]))
        else:
            await _reply_menu_text(update, _ui_card("Источник", ["ℹ️ Источник не найден."]))
        return

    if mode == MODE_GREEN_ORDER_DONOR:
        draft = context.user_data.get("green_order")
        if not isinstance(draft, dict):
            draft = {}
        draft["donor_link"] = text
        context.user_data["green_order"] = draft
        context.user_data["input_mode"] = MODE_GREEN_ORDER_NAME
        await update.message.reply_text(
            _ui_card("Заказ у зелёных · Шаг 2/5", ["Фамилия Имя."], _back_hint()),
            parse_mode=ParseMode.HTML,
            reply_markup=_back_menu(),
        )
        return

    if mode == MODE_GREEN_ORDER_NAME:
        draft = context.user_data.get("green_order")
        if not isinstance(draft, dict):
            draft = {}
        draft["full_name"] = text
        context.user_data["green_order"] = draft
        context.user_data["input_mode"] = MODE_GREEN_ORDER_DOB
        await update.message.reply_text(
            _ui_card("Заказ у зелёных · Шаг 3/5", ["Дата рождения (полная)."], _back_hint()),
            parse_mode=ParseMode.HTML,
            reply_markup=_back_menu(),
        )
        return

    if mode == MODE_GREEN_ORDER_DOB:
        draft = context.user_data.get("green_order")
        if not isinstance(draft, dict):
            draft = {}
        draft["birth_date"] = text
        context.user_data["green_order"] = draft
        context.user_data["input_mode"] = MODE_GREEN_ORDER_COUNT
        await update.message.reply_text(
            _ui_card("Заказ у зелёных · Шаг 4/5", ["Количество (число)."], _back_hint()),
            parse_mode=ParseMode.HTML,
            reply_markup=_back_menu(),
        )
        return

    if mode == MODE_GREEN_ORDER_COUNT:
        parsed = _parse_report767_single_number(text)
        if parsed is None:
            await update.message.reply_text(
                _ui_card("Заказ у зелёных", ["Нужно ввести число количества."], _back_hint()),
                parse_mode=ParseMode.HTML,
                reply_markup=_back_menu(),
            )
            return
        draft = context.user_data.get("green_order")
        if not isinstance(draft, dict):
            draft = {}
        draft["count"] = int(parsed)
        context.user_data["green_order"] = draft
        context.user_data["input_mode"] = MODE_GREEN_ORDER_VK
        await update.message.reply_text(
            _ui_card("Заказ у зелёных · Шаг 5/5", ["Название источника VK."], _back_hint()),
            parse_mode=ParseMode.HTML,
            reply_markup=_back_menu(),
        )
        return

    if mode == MODE_GREEN_ORDER_VK:
        draft = context.user_data.get("green_order")
        if not isinstance(draft, dict):
            draft = {}
        draft["vk_source"] = text
        context.user_data["green_order"] = draft

        created_at = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
        entry = {
            "created_at": created_at,
            "chat_id": int(update.effective_chat.id) if update.effective_chat else 0,
            "user_id": int(update.effective_user.id) if update.effective_user else 0,
            "username": (update.effective_user.username or "") if update.effective_user else "",
            "donor_link": draft.get("donor_link", ""),
            "full_name": draft.get("full_name", ""),
            "birth_date": draft.get("birth_date", ""),
            "count": int(draft.get("count", 0) or 0),
            "vk_source": draft.get("vk_source", ""),
        }

        try:
            _insert_green_order(entry)
        except sqlite3.Error as exc:
            context.user_data.pop("input_mode", None)
            context.user_data.pop("green_order", None)
            await _reply_menu_text(update, f"❌ Ошибка записи заказа: <code>{exc}</code>")
            return

        context.user_data.pop("input_mode", None)
        context.user_data.pop("green_order", None)

        lines = [
            "Ссылка на донора (Instagram/Telegram-канал)",
            entry.get("donor_link", "—"),
            "",
            "Фамилия Имя",
            entry.get("full_name", "—"),
            "Дата рождения полная",
            entry.get("birth_date", "—"),
            "",
            f"{entry.get('count', 0)} вк ({entry.get('vk_source', '—')})",
        ]
        order_text = _compact_lines(lines)
        sent_ok, sent_err = await _send_green_order_to_group(context, order_text)
        if sent_ok:
            await _reply_menu_text(
                update,
                _ui_card("Заказ у зелёных", [order_text, "✅ Отправлено в группу."]),
            )
        else:
            await _reply_menu_text(
                update,
                _ui_card("Заказ у зелёных", [order_text, f"⚠️ Не отправлено в группу: {sent_err}"]),
            )
        return

    if mode == MODE_REPORT_767_ACCESS_ADD:
        admin_chat_ids: Set[int] = context.application.bot_data.get("admin_chat_ids", set())
        if not _is_admin_chat(update, admin_chat_ids):
            context.user_data.pop("input_mode", None)
            await _reply_menu_text(update, "⛔ Доступ к админке запрещен.")
            return
        parsed = _parse_report767_single_number(text)
        if parsed is None:
            await update.message.reply_text(
                _ui_card(
                    "Доступ к итогам 767",
                    ["Нужен один числовой chat_id.", "Пример: <code>123456789</code>"],
                    _back_hint(),
                ),
                parse_mode=ParseMode.HTML,
                reply_markup=_back_menu(),
            )
            return
        try:
            _report767_access_add(int(parsed), update)
        except sqlite3.Error as exc:
            context.user_data.pop("input_mode", None)
            await _reply_menu_text(update, f"❌ Ошибка добавления доступа: <code>{exc}</code>")
            return
        context.user_data.pop("input_mode", None)
        await _reply_menu_text(update, f"✅ Доступ к итогам 767 выдан для chat_id <code>{parsed}</code>.")
        return

    if mode == MODE_REPORT_767_ACCESS_REMOVE:
        admin_chat_ids: Set[int] = context.application.bot_data.get("admin_chat_ids", set())
        if not _is_admin_chat(update, admin_chat_ids):
            context.user_data.pop("input_mode", None)
            await _reply_menu_text(update, "⛔ Доступ к админке запрещен.")
            return
        parsed = _parse_report767_single_number(text)
        if parsed is None:
            await update.message.reply_text(
                _ui_card(
                    "Снятие доступа к итогам 767",
                    ["Нужен один числовой chat_id.", "Пример: <code>123456789</code>"],
                    _back_hint(),
                ),
                parse_mode=ParseMode.HTML,
                reply_markup=_back_menu(),
            )
            return
        try:
            removed = _report767_access_remove(int(parsed))
        except sqlite3.Error as exc:
            context.user_data.pop("input_mode", None)
            await _reply_menu_text(update, f"❌ Ошибка удаления доступа: <code>{exc}</code>")
            return
        context.user_data.pop("input_mode", None)
        if removed:
            await _reply_menu_text(update, f"✅ Доступ к итогам 767 снят для chat_id <code>{parsed}</code>.")
        else:
            await _reply_menu_text(update, f"ℹ️ chat_id <code>{parsed}</code> не найден в списке.")
        return

    if mode == MODE_ADMIN_ROLE_ADD_HEAD:
        admin_chat_ids: Set[int] = context.application.bot_data.get("admin_chat_ids", set())
        if not _is_admin_chat(update, admin_chat_ids):
            context.user_data.pop("input_mode", None)
            await _reply_menu_text(update, "⛔ Доступ к админке запрещен.")
            return
        parsed = _parse_report767_single_number(text)
        if parsed is None:
            await update.message.reply_text(
                _ui_card(
                    "Выдача роли head",
                    ["Нужен один числовой chat_id.", "Пример: <code>123456789</code>"],
                    _back_hint(),
                ),
                parse_mode=ParseMode.HTML,
                reply_markup=_back_menu(),
            )
            return
        try:
            _roles_set(int(parsed), "head", update)
        except sqlite3.Error as exc:
            context.user_data.pop("input_mode", None)
            await _reply_menu_text(update, f"❌ Ошибка записи роли: <code>{exc}</code>")
            return
        context.user_data.pop("input_mode", None)
        await _reply_menu_text(update, f"✅ Роль <b>head</b> выдана для chat_id <code>{parsed}</code>.")
        return

    if mode == MODE_ADMIN_ROLE_ADD_TEAM:
        admin_chat_ids: Set[int] = context.application.bot_data.get("admin_chat_ids", set())
        if not _is_admin_chat(update, admin_chat_ids):
            context.user_data.pop("input_mode", None)
            await _reply_menu_text(update, "⛔ Доступ к админке запрещен.")
            return
        parsed = _parse_report767_single_number(text)
        if parsed is None:
            await update.message.reply_text(
                _ui_card(
                    "Выдача роли team",
                    ["Нужен один числовой chat_id.", "Пример: <code>123456789</code>"],
                    _back_hint(),
                ),
                parse_mode=ParseMode.HTML,
                reply_markup=_back_menu(),
            )
            return
        try:
            _roles_set(int(parsed), "team", update)
        except sqlite3.Error as exc:
            context.user_data.pop("input_mode", None)
            await _reply_menu_text(update, f"❌ Ошибка записи роли: <code>{exc}</code>")
            return
        context.user_data.pop("input_mode", None)
        await _reply_menu_text(update, f"✅ Роль <b>team</b> выдана для chat_id <code>{parsed}</code>.")
        return

    if mode == MODE_ADMIN_ROLE_REMOVE:
        admin_chat_ids: Set[int] = context.application.bot_data.get("admin_chat_ids", set())
        if not _is_admin_chat(update, admin_chat_ids):
            context.user_data.pop("input_mode", None)
            await _reply_menu_text(update, "⛔ Доступ к админке запрещен.")
            return
        parsed = _parse_report767_single_number(text)
        if parsed is None:
            await update.message.reply_text(
                _ui_card(
                    "Удаление роли",
                    ["Нужен один числовой chat_id.", "Пример: <code>123456789</code>"],
                    _back_hint(),
                ),
                parse_mode=ParseMode.HTML,
                reply_markup=_back_menu(),
            )
            return
        try:
            removed = _roles_remove(int(parsed))
        except sqlite3.Error as exc:
            context.user_data.pop("input_mode", None)
            await _reply_menu_text(update, f"❌ Ошибка удаления роли: <code>{exc}</code>")
            return
        context.user_data.pop("input_mode", None)
        if removed:
            await _reply_menu_text(update, f"✅ Роль удалена для chat_id <code>{parsed}</code>.")
        else:
            await _reply_menu_text(update, f"ℹ️ chat_id <code>{parsed}</code> не найден в списке ролей.")
        return

    if mode == MODE_REPORT_767_TEAM:
        team = text.strip().lower()
        if team not in REPORT_767_TEAMS:
            await _reply_menu_text(
                update,
                _ui_card(
                    "Отчёт 767 · Шаг 1/7",
                    [
                        "❌ Некорректная тима.",
                        "Выбери одну из кнопок: <code>kizaru1312</code>, <code>apathy7</code>, <code>stil1x315</code>.",
                    ],
                    _back_hint(),
                ),
                reply_markup=_back_menu(),
            )
            await update.message.reply_text(
                "🧩 Доступные тимы:",
                reply_markup=_report767_team_inline(),
            )
            return

        draft = context.user_data.get("report767_draft")
        if not isinstance(draft, dict):
            draft = {}
        draft["team"] = team
        context.user_data["report767_draft"] = draft
        context.user_data["input_mode"] = MODE_REPORT_767_NUMBERS_TO_CHECK
        await update.message.reply_text(
            _ui_card(
                "Отчёт 767 · Шаг 2/7",
                ["Введи <b>номеров на проверку</b> (одно число)."],
                _back_hint(),
            ),
            parse_mode=ParseMode.HTML,
            reply_markup=_back_menu(),
        )
        return

    if mode == MODE_REPORT_767_NUMBERS_TO_CHECK:
        parsed = _parse_report767_single_number(text)
        if parsed is None:
            await update.message.reply_text(
                _ui_card(
                    "Отчёт 767 · Шаг 2/7",
                    ["❌ Нужен один номер.", "Пример: <code>120</code>"],
                    _back_hint(),
                ),
                parse_mode=ParseMode.HTML,
                reply_markup=_back_menu(),
            )
            return

        numbers_to_check = parsed
        draft = context.user_data.get("report767_draft")
        if not isinstance(draft, dict):
            draft = {}
        draft["numbers_to_check"] = numbers_to_check
        context.user_data["report767_draft"] = draft
        context.user_data["input_mode"] = MODE_REPORT_767_POSITIVES
        await update.message.reply_text(
            _ui_card(
                "Отчёт 767 · Шаг 3/7",
                ["Введи <b>плюсовых</b> (одно число)."],
                _back_hint(),
            ),
            parse_mode=ParseMode.HTML,
            reply_markup=_back_menu(),
        )
        return

    if mode == MODE_REPORT_767_POSITIVES:
        parsed = _parse_report767_single_number(text)
        if parsed is None:
            await update.message.reply_text(
                _ui_card(
                    "Отчёт 767 · Шаг 3/7",
                    ["❌ Нужен один номер.", "Пример: <code>10</code>"],
                    _back_hint(),
                ),
                parse_mode=ParseMode.HTML,
                reply_markup=_back_menu(),
            )
            return

        draft = context.user_data.get("report767_draft")
        if not isinstance(draft, dict):
            draft = {}
        draft["positives"] = parsed
        context.user_data["report767_draft"] = draft
        context.user_data["input_mode"] = MODE_REPORT_767_ACTIVE
        await update.message.reply_text(
            _ui_card(
                "Отчёт 767 · Шаг 4/7",
                ["Введи <b>актив</b> (одно число)."],
                _back_hint(),
            ),
            parse_mode=ParseMode.HTML,
            reply_markup=_back_menu(),
        )
        return

    if mode == MODE_REPORT_767_ACTIVE:
        parsed = _parse_report767_single_number(text)
        if parsed is None:
            await update.message.reply_text(
                _ui_card(
                    "Отчёт 767 · Шаг 4/7",
                    ["❌ Нужен один номер.", "Пример: <code>7</code>"],
                    _back_hint(),
                ),
                parse_mode=ParseMode.HTML,
                reply_markup=_back_menu(),
            )
            return

        draft = context.user_data.get("report767_draft")
        if not isinstance(draft, dict):
            draft = {}
        draft["active"] = parsed
        context.user_data["report767_draft"] = draft
        context.user_data["input_mode"] = MODE_REPORT_767_VBROS
        await update.message.reply_text(
            _ui_card(
                "Отчёт 767 · Шаг 5/7",
                ["Введи <b>вброс</b> (одно число)."],
                _back_hint(),
            ),
            parse_mode=ParseMode.HTML,
            reply_markup=_back_menu(),
        )
        return

    if mode == MODE_REPORT_767_VBROS:
        parsed = _parse_report767_single_number(text)
        if parsed is None:
            await update.message.reply_text(
                _ui_card(
                    "Отчёт 767 · Шаг 5/7",
                    ["❌ Нужен один номер.", "Пример: <code>3</code>"],
                    _back_hint(),
                ),
                parse_mode=ParseMode.HTML,
                reply_markup=_back_menu(),
            )
            return

        draft = context.user_data.get("report767_draft")
        if not isinstance(draft, dict):
            draft = {}
        draft["vbros"] = parsed
        context.user_data["report767_draft"] = draft
        context.user_data["input_mode"] = MODE_REPORT_767_PREDLOG
        await update.message.reply_text(
            _ui_card(
                "Отчёт 767 · Шаг 6/7",
                ["Введи <b>предлог</b> (одно число)."],
                _back_hint(),
            ),
            parse_mode=ParseMode.HTML,
            reply_markup=_back_menu(),
        )
        return

    if mode == MODE_REPORT_767_PREDLOG:
        parsed = _parse_report767_single_number(text)
        if parsed is None:
            await update.message.reply_text(
                _ui_card(
                    "Отчёт 767 · Шаг 6/7",
                    ["❌ Нужен один номер.", "Пример: <code>2</code>"],
                    _back_hint(),
                ),
                parse_mode=ParseMode.HTML,
                reply_markup=_back_menu(),
            )
            return

        draft = context.user_data.get("report767_draft")
        if not isinstance(draft, dict):
            draft = {}
        draft["predlog"] = parsed
        context.user_data["report767_draft"] = draft
        context.user_data["input_mode"] = MODE_REPORT_767_SOGLASIY
        await update.message.reply_text(
            _ui_card(
                "Отчёт 767 · Шаг 7/7",
                ["Введи <b>согласий</b> (одно число)."],
                _back_hint(),
            ),
            parse_mode=ParseMode.HTML,
            reply_markup=_back_menu(),
        )
        return

    if mode == MODE_REPORT_767_SOGLASIY:
        parsed = _parse_report767_single_number(text)
        if parsed is None:
            await update.message.reply_text(
                _ui_card(
                    "Отчёт 767 · Шаг 7/7",
                    ["❌ Нужен один номер.", "Пример: <code>1</code>"],
                    _back_hint(),
                ),
                parse_mode=ParseMode.HTML,
                reply_markup=_back_menu(),
            )
            return

        soglasiy = parsed
        draft = context.user_data.get("report767_draft")
        if not isinstance(draft, dict):
            draft = {}

        team = str(draft.get("team", "")).strip().lower()
        if team not in REPORT_767_TEAMS:
            context.user_data.pop("input_mode", None)
            context.user_data.pop("report767_draft", None)
            await _reply_menu_text(
                update,
                _ui_card(
                    "Отчёт 767",
                    ["❌ Сессия устарела. Нажми кнопку <b>Отчёт 767</b> и начни заново."],
                ),
            )
            return

        numbers_to_check = int(draft.get("numbers_to_check", 0) or 0)
        positives = int(draft.get("positives", 0) or 0)
        active = int(draft.get("active", 0) or 0)
        vbros = int(draft.get("vbros", 0) or 0)
        predlog = int(draft.get("predlog", 0) or 0)
        author = ""
        if update.effective_user:
            if update.effective_user.username:
                author = f"@{update.effective_user.username}"
            else:
                author = " ".join(
                    p for p in [update.effective_user.first_name, update.effective_user.last_name] if p
                ).strip()

        created_at = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
        entry = {
            "created_at": created_at,
            "chat_id": int(update.effective_chat.id) if update.effective_chat else 0,
            "user_id": int(update.effective_user.id) if update.effective_user else 0,
            "username": (update.effective_user.username or "") if update.effective_user else "",
            "author": author,
            "team": team,
            "reports_done": 0,
            "reports_plan": 0,
            "numbers_to_check": numbers_to_check,
            "positives": positives,
            "active": active,
            "vbros": vbros,
            "predlog": predlog,
            "soglasiy": soglasiy,
        }

        try:
            _insert_report767_entry(entry)
            gs_ok, gs_err = _append_report767_to_gsheets(entry)
            show_totals = _is_report767_stats_allowed(update, context.application.bot_data)
            team_totals = _get_report767_totals(team) if show_totals else {}
            all_totals = _get_report767_totals() if show_totals else {}
        except sqlite3.Error as exc:
            context.user_data.pop("input_mode", None)
            context.user_data.pop("report767_draft", None)
            await _reply_menu_text(update, f"❌ Ошибка записи в таблицу 767: <code>{exc}</code>")
            return

        context.user_data.pop("input_mode", None)
        context.user_data.pop("report767_draft", None)

        author_line = f"• Автор: <code>{author}</code>" if author else ""
        lines = ["✅ <b>Отчёт 767 сохранён</b>", f"• Тима: <code>{team}</code>"]
        if author_line:
            lines.append(author_line)
        lines.extend([
            f"• Номеров на проверку: <b>{numbers_to_check}</b>",
            f"• Плюсовых: <b>{positives}</b>",
            f"• Актив: <b>{active}</b>",
            f"• Вброс: <b>{vbros}</b>",
            f"• Предлог: <b>{predlog}</b>",
            f"• Согласий: <b>{soglasiy}</b>",
            "",
        ])
        if not gs_ok:
            lines.append(f"⚠️ Google Sheets: {gs_err or 'не настроено'}")
            lines.append("")
        if show_totals:
            lines.extend(_format_report767_totals(f"Итоги по тиме <code>{team}</code>", team_totals))
            lines.append("")
            lines.extend(_format_report767_totals("Общие итоги", all_totals))
        await _reply_menu_text(update, _compact_lines(lines))
        return

    if mode == "tg_catalog":
        context.user_data.pop("input_mode", None)
        await _run_tg_catalog_search_and_reply(update, text)
        return

    lowered = text.lower()
    if text.startswith("@") or lowered.startswith("t.me/") or lowered.startswith("https://t.me/") or lowered.startswith("http://t.me/"):
        await _run_tg_search_and_reply(update, text)
        return

    phone = text
    await _run_search_and_reply(update, phone)


def build_app(token: str) -> Application:
    app = Application.builder().token(token).build()
    app.add_error_handler(_error_handler)
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("search", search_cmd))
    app.add_handler(CommandHandler("ip", ip_cmd))
    app.add_handler(CommandHandler("email", email_cmd))
    app.add_handler(CommandHandler("tg", tg_cmd))
    app.add_handler(CommandHandler("tgcat", tg_catalog_cmd))
    app.add_handler(CommandHandler("topchannels", top_channels_cmd))
    app.add_handler(CommandHandler("topchats", top_chats_cmd))
    app.add_handler(CommandHandler("randomtg", random_tg_cmd))
    app.add_handler(CommandHandler("id", id_cmd))
    app.add_handler(CommandHandler("uptime", uptime_cmd))
    app.add_handler(CommandHandler("report767", report767_cmd))
    app.add_handler(CommandHandler("report767stats", report767_stats_cmd))
    app.add_handler(CommandHandler("admin", admin_cmd))
    app.add_handler(CommandHandler("fssp", fssp_cmd))
    app.add_handler(CallbackQueryHandler(report767_callback, pattern=r"^report767:"))
    app.add_handler(CallbackQueryHandler(source_callback, pattern=r"^source:"))
    app.add_handler(CallbackQueryHandler(admin_callback, pattern=r"^admin:"))
    app.add_handler(MessageHandler(filters.COMMAND, unknown_cmd))
    app.add_handler(MessageHandler(filters.PHOTO, photo_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_fallback))
    return app


def run_sync() -> None:
    lock = SingleInstanceLock()
    try:
        with lock:
            asyncio.run(run())
    except RuntimeError as exc:
        logger.error("%s", exc)
        raise SystemExit(2) from exc


async def _run_bot_instance(
    token: str,
    allowed_chat_ids: Set[int],
    admin_chat_ids: Set[int],
    green_order_chat_id: Optional[int],
    green_order_thread_id: Optional[int],
) -> None:
    global _RUNTIME_ADMIN_CHAT_IDS
    _RUNTIME_ADMIN_CHAT_IDS = set(admin_chat_ids)

    app = build_app(token)
    app.bot_data["allowed_chat_ids"] = allowed_chat_ids
    app.bot_data["admin_chat_ids"] = admin_chat_ids
    app.bot_data["green_order_chat_id"] = green_order_chat_id
    app.bot_data["green_order_thread_id"] = green_order_thread_id
    app.bot_data["started_at_ts"] = time.time()

    try:
        _ensure_report767_table()
        _ensure_report767_access_table()
        _ensure_roles_table()
        _ensure_sources_table()
        _ensure_source_orders_table()
        logger.info("Report767 table ready: %s", REPORT_767_DB_PATH)
    except sqlite3.Error as exc:
        logger.warning("Report767 table init failed: %s", exc)

    if allowed_chat_ids:
        logger.info("Telegram bot access control enabled for %d chat(s)", len(allowed_chat_ids))
    else:
        logger.info("Telegram bot access control disabled (all chats allowed)")

    if admin_chat_ids:
        logger.info("Telegram admin panel enabled for %d admin chat(s)", len(admin_chat_ids))
    else:
        logger.info("Telegram admin panel disabled (TELEGRAM_ADMIN_CHAT_IDS is empty)")

    if green_order_chat_id:
        logger.info("Green orders group enabled: %s", green_order_chat_id)
    else:
        logger.info("Green orders group not configured (missing GREEN_ORDER_CHAT_ID)")

    reports_dir = os.getenv("REPORTS_PUBLIC_DIR", "").strip()
    reports_url = os.getenv("REPORTS_BASE_URL", "").strip()
    if _REPORTLAB_AVAILABLE and reports_dir and reports_url:
        logger.info("PDF reports enabled: %s -> %s", reports_dir, reports_url)
    else:
        logger.info("PDF reports disabled or partially configured (need reportlab + REPORTS_PUBLIC_DIR + REPORTS_BASE_URL)")

    if _GSHEETS_AVAILABLE:
        if os.getenv("GOOGLE_SHEETS_ID", "").strip():
            logger.info("Google Sheets integration enabled")
        else:
            logger.info("Google Sheets integration not configured (missing GOOGLE_SHEETS_ID)")
    else:
        logger.info("Google Sheets integration disabled (missing gspread/google-auth)")

    logger.info("Telegram bot started")
    try:
        await app.initialize()
        await app.start()
        if app.updater is None:
            raise RuntimeError("Updater is not available; cannot start polling.")
        await app.updater.start_polling()

        while True:
            await asyncio.sleep(3600)
    finally:
        with contextlib.suppress(Exception):
            if app.updater:
                await app.updater.stop()
        with contextlib.suppress(Exception):
            await app.stop()
        with contextlib.suppress(Exception):
            await app.shutdown()


async def run() -> None:
    load_dotenv()
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set. Add it to .env file.")

    allowed_chat_ids = _parse_allowed_chat_ids(os.getenv("TELEGRAM_ALLOWED_CHAT_IDS", ""))
    admin_chat_ids = _parse_admin_chat_ids(os.getenv("TELEGRAM_ADMIN_CHAT_IDS", ""))
    green_order_chat_id = _parse_optional_int(os.getenv("GREEN_ORDER_CHAT_ID", ""))
    green_order_thread_id = _parse_optional_int(os.getenv("GREEN_ORDER_THREAD_ID", ""))

    backoff_seconds = 5
    max_backoff = 300
    while True:
        try:
            await _run_bot_instance(
                token,
                allowed_chat_ids,
                admin_chat_ids,
                green_order_chat_id,
                green_order_thread_id,
            )
        except (KeyboardInterrupt, SystemExit, asyncio.CancelledError):
            logger.info("Stopping Telegram bot")
            break
        except Exception:
            logger.exception("Telegram bot crashed. Restarting in %s seconds", backoff_seconds)
            await asyncio.sleep(backoff_seconds)
            backoff_seconds = min(backoff_seconds * 2, max_backoff)
        else:
            logger.warning("Telegram bot stopped without error. Restarting in %s seconds", backoff_seconds)
            await asyncio.sleep(backoff_seconds)
            backoff_seconds = min(backoff_seconds * 2, max_backoff)


if __name__ == "__main__":
    run_sync()
