#!/usr/bin/env python3
"""Second Telegram bot instance for quick phone checks.

Uses dedicated env vars and lock file so it can run in parallel with telegram_bot.py.
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Set
from urllib.parse import quote, urlencode

from dotenv import load_dotenv
import requests
from telegram import KeyboardButton, ReplyKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from universal_search_system import universal_search


logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN_ENV = "TELEGRAM_BOT_TOKEN_COPY"
ALLOWED_CHAT_IDS_ENV = "TELEGRAM_ALLOWED_CHAT_IDS_COPY"
FSSP_TOKEN_ENV = "FSSP_API_TOKEN_COPY"

BTN_PHONE = "📞 Поиск номера"
BTN_PHOTO = "🖼 Поиск по фото"
BTN_FSSP = "⚖️ ФССП"
BTN_HELP = "ℹ️ Помощь"


def _main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(BTN_PHONE), KeyboardButton(BTN_PHOTO)],
            [KeyboardButton(BTN_FSSP), KeyboardButton(BTN_HELP)],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
        selective=False,
    )


class SingleInstanceLock:
    """Cross-platform non-blocking lock to prevent duplicate bot instances."""

    def __init__(self, lock_name: str = "phoneinfoga_telegram_bot_copy.lock"):
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
            logger.warning("Invalid %s value ignored: %s", ALLOWED_CHAT_IDS_ENV, value)
    return allowed


def _is_chat_allowed(update: Update, allowed_chat_ids: Set[int]) -> bool:
    if not allowed_chat_ids:
        return True
    if not update.effective_chat:
        return False
    return int(update.effective_chat.id) in allowed_chat_ids


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


def _safe_get(d: Dict[str, Any], *keys: str, default: Any = "—") -> Any:
    current: Any = d
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


def _format_result(payload: Dict[str, Any]) -> str:
    if not payload.get("valid"):
        err = payload.get("error", "Не удалось обработать номер")
        return f"❌ {err}"

    basic = _safe_get(payload, "results", "basic", default={})
    owner = _safe_get(payload, "results", "owner", default={})
    breaches = _safe_get(payload, "results", "data_breaches", default={})

    lines = [
        "✅ <b>Результат проверки</b>",
        f"📞 Ввод: <code>{payload.get('input', '—')}</code>",
        f"🌍 E.164: <code>{payload.get('formatted', '—')}</code>",
        "",
        "<b>Базовая информация</b>",
        f"• Страна/регион: {_safe_get(basic, 'country')} ({_safe_get(basic, 'region_code')})",
        f"• Оператор: {_safe_get(basic, 'carrier')}",
        f"• Международный формат: <code>{_safe_get(basic, 'international_format')}</code>",
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


def _arg_from_context(context: ContextTypes.DEFAULT_TYPE) -> str:
    return " ".join(context.args).strip() if context.args else ""


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    allowed_chat_ids: Set[int] = context.application.bot_data.get("allowed_chat_ids", set())
    if await _deny_if_not_allowed(update, allowed_chat_ids):
        return

    if not update.message:
        return

    text = (
        "Привет! Я бот для быстрой проверки телефонных номеров в формате OSINT.\n\n"
        "Нажимай кнопки ниже или используй команды.\n\n"
        "Команды:\n"
        "• /start — старт\n"
        "• /help — помощь\n"
        "• /search <номер> — проверить номер\n"
        "• /ip <адрес> — информация по IP\n"
        "• /email <адрес> — базовая проверка email\n\n"
        "• /fssp <ФИО;дата;регион> — проверка ФССП (официальный API)\n\n"
        "• Отправьте фото — бот даст reverse search по интернету и VK\n\n"
        "Пример: <code>/search +79001234567</code>\n"
        "Также можно просто отправить номер сообщением."
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=_main_menu())


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    allowed_chat_ids: Set[int] = context.application.bot_data.get("allowed_chat_ids", set())
    if await _deny_if_not_allowed(update, allowed_chat_ids):
        return

    if not update.message:
        return

    await update.message.reply_text(
        "Доступные команды:\n"
        "• <code>/search +79001234567</code> — проверка телефона\n"
        "• <code>/ip 8.8.8.8</code> — IP lookup\n"
        "• <code>/email test@example.com</code> — проверка email\n\n"
        "• <code>/fssp Иванов Иван Иванович;1990-01-01;77</code> — ФССП по ФИО\n\n"
        "• Отправьте фото в чат — бот подготовит ссылки reverse image search и VK-поиска\n\n"
        "Или просто отправьте номер телефона отдельным сообщением.",
        parse_mode=ParseMode.HTML,
        reply_markup=_main_menu(),
    )


async def _run_search_and_reply(update: Update, phone: str) -> None:
    if not update.message:
        return

    await update.message.reply_text("⏳ Ищу информацию, секунду...")
    payload = universal_search.universal_phone_search(
        phone,
        ["basic", "owner", "data_breaches", "ru_resources"],
    )
    await update.message.reply_text(_format_result(payload), parse_mode=ParseMode.HTML)


async def search_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    allowed_chat_ids: Set[int] = context.application.bot_data.get("allowed_chat_ids", set())
    if await _deny_if_not_allowed(update, allowed_chat_ids):
        return

    if not update.message:
        return

    if not context.args:
        await update.message.reply_text("Укажи номер: <code>/search +79001234567</code>", parse_mode=ParseMode.HTML)
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
        await update.message.reply_text("Укажи IP: <code>/ip 8.8.8.8</code>", parse_mode=ParseMode.HTML)
        return

    await update.message.reply_text("⏳ Проверяю IP...")
    payload = universal_search.xosint.ip_lookup(value)
    await update.message.reply_text(_format_ip_result(payload), parse_mode=ParseMode.HTML)


async def email_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    allowed_chat_ids: Set[int] = context.application.bot_data.get("allowed_chat_ids", set())
    if await _deny_if_not_allowed(update, allowed_chat_ids):
        return

    if not update.message:
        return

    value = _arg_from_context(context)
    if not value:
        await update.message.reply_text(
            "Укажи email: <code>/email test@example.com</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    await update.message.reply_text("⏳ Проверяю email...")
    payload = universal_search.xosint.email_check(value)
    await update.message.reply_text(_format_email_result(payload), parse_mode=ParseMode.HTML)


async def fssp_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    allowed_chat_ids: Set[int] = context.application.bot_data.get("allowed_chat_ids", set())
    if await _deny_if_not_allowed(update, allowed_chat_ids):
        return

    if not update.message:
        return

    value = _arg_from_context(context)
    if not value:
        await update.message.reply_text(
            "Формат: <code>/fssp Иванов Иван Иванович;1990-01-01;77</code>\n"
            "Где: ФИО;дата рождения (опц.);код региона (опц.).",
            parse_mode=ParseMode.HTML,
        )
        return

    token = os.getenv(FSSP_TOKEN_ENV, "").strip() or os.getenv("FSSP_API_TOKEN", "").strip()
    if not token:
        await update.message.reply_text(
            f"⚠️ Не задан <code>{FSSP_TOKEN_ENV}</code> (или <code>FSSP_API_TOKEN</code>) в .env.\n"
            "Пока можно проверить вручную на официальном сервисе: https://fssp.gov.ru/iss/ip",
            parse_mode=ParseMode.HTML,
        )
        return

    try:
        parsed = _parse_fssp_input(value)
    except ValueError as exc:
        await update.message.reply_text(f"❌ {exc}", parse_mode=ParseMode.HTML)
        return

    await update.message.reply_text("⏳ Проверяю ФССП по официальному API...")
    try:
        result = _fssp_official_search(parsed, token)
        await update.message.reply_text(_format_fssp_result(parsed, result), parse_mode=ParseMode.HTML)
    except (requests.RequestException, RuntimeError, ValueError) as exc:
        await update.message.reply_text(
            "❌ Ошибка запроса ФССП API.\n"
            f"Детали: <code>{str(exc)}</code>\n"
            "Проверьте токен/формат данных или используйте https://fssp.gov.ru/iss/ip",
            parse_mode=ParseMode.HTML,
        )


async def photo_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    allowed_chat_ids: Set[int] = context.application.bot_data.get("allowed_chat_ids", set())
    if await _deny_if_not_allowed(update, allowed_chat_ids):
        return

    if not update.message or not update.message.photo:
        return

    await update.message.reply_text("⏳ Анализирую фото и готовлю ссылки для интернета и VK...")

    # Highest resolution photo from Telegram message.
    photo = update.message.photo[-1]
    tg_file = await context.bot.get_file(photo.file_id)

    with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
        tmp_path = tmp.name

    try:
        await tg_file.download_to_drive(custom_path=tmp_path)
        photo_result = universal_search.universal_photo_search(tmp_path, ["metadata", "search_engines"])

        token = os.getenv(BOT_TOKEN_ENV, "").strip()
        file_url = ""
        if token and getattr(tg_file, "file_path", ""):
            file_url = f"https://api.telegram.org/file/bot{token}/{tg_file.file_path}"

        query_hint = update.message.caption or _safe_get(photo_result, "results", "metadata", "filename", default="")
        vk_links = _build_vk_photo_links(file_url, str(query_hint))

        await update.message.reply_text(_format_photo_result(photo_result, vk_links), parse_mode=ParseMode.HTML)
    except (requests.RequestException, OSError, ValueError, RuntimeError) as exc:
        await update.message.reply_text(f"❌ Ошибка анализа фото: <code>{str(exc)}</code>", parse_mode=ParseMode.HTML)
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


async def text_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    allowed_chat_ids: Set[int] = context.application.bot_data.get("allowed_chat_ids", set())
    if await _deny_if_not_allowed(update, allowed_chat_ids):
        return

    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()

    # UI keyboard button actions
    if text == BTN_PHONE:
        await update.message.reply_text(
            "Введи номер в международном формате, например: <code>+79001234567</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=_main_menu(),
        )
        return

    if text == BTN_PHOTO:
        await update.message.reply_text(
            "Пришли фото в чат — я подготовлю reverse image search ссылки по интернету и VK.",
            reply_markup=_main_menu(),
        )
        return

    if text == BTN_FSSP:
        await update.message.reply_text(
            "Формат: <code>/fssp Иванов Иван Иванович;1990-01-01;77</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=_main_menu(),
        )
        return

    if text == BTN_HELP:
        await help_cmd(update, context)
        return

    phone = text
    await _run_search_and_reply(update, phone)


def build_app(token: str) -> Application:
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("search", search_cmd))
    app.add_handler(CommandHandler("ip", ip_cmd))
    app.add_handler(CommandHandler("email", email_cmd))
    app.add_handler(CommandHandler("fssp", fssp_cmd))
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


async def run() -> None:
    load_dotenv()
    token = os.getenv(BOT_TOKEN_ENV, "").strip()
    if not token:
        raise RuntimeError(f"{BOT_TOKEN_ENV} is not set. Add it to .env file.")

    allowed_chat_ids = _parse_allowed_chat_ids(os.getenv(ALLOWED_CHAT_IDS_ENV, ""))

    app = build_app(token)
    app.bot_data["allowed_chat_ids"] = allowed_chat_ids

    if allowed_chat_ids:
        logger.info("Telegram bot copy access control enabled for %d chat(s)", len(allowed_chat_ids))
    else:
        logger.info("Telegram bot copy access control disabled (all chats allowed)")

    logger.info("Telegram bot copy started")
    await app.initialize()
    await app.start()
    await app.updater.start_polling()

    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Stopping Telegram bot")
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()


if __name__ == "__main__":
    run_sync()
