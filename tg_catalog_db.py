"""Telegram chats/channels catalog DB utilities."""

from __future__ import annotations

import os
import re
import sqlite3
import zipfile
import xml.etree.ElementTree as ET
from typing import Dict, Iterable, List, Optional, Tuple


DEFAULT_DB_PATH = "tg_catalog.db"

_NS = {
    "a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}


def get_db_path() -> str:
    return os.getenv("TG_CATALOG_DB_PATH", DEFAULT_DB_PATH)


def init_db(db_path: str = DEFAULT_DB_PATH) -> None:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS tg_catalog (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_type TEXT NOT NULL,         -- "chat" | "channel"
            title TEXT,
            link TEXT,
            username TEXT,
            members INTEGER,
            comments_mode TEXT,                -- channels
            can_write TEXT,                    -- chats
            members_list_mode TEXT,            -- chats
            forum_mode TEXT,                   -- chats
            description TEXT
        )
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_tg_catalog_type ON tg_catalog(source_type)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_tg_catalog_username ON tg_catalog(username)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_tg_catalog_title ON tg_catalog(title)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_tg_catalog_link ON tg_catalog(link)")
    conn.commit()
    conn.close()


def _connect(db_path: Optional[str] = None) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path or get_db_path())
    conn.row_factory = sqlite3.Row
    return conn


def _normalize_username(raw: str) -> str:
    value = (raw or "").strip().lower()
    if not value:
        return ""

    for prefix in ("https://t.me/", "http://t.me/", "t.me/"):
        if value.startswith(prefix):
            value = value[len(prefix) :]
            break

    if value.startswith("@"):
        value = value[1:]

    value = value.split("?", 1)[0].split("/", 1)[0].strip()
    if not value:
        return ""

    # Telegram username chars only.
    filtered = re.sub(r"[^a-z0-9_]", "", value)
    return filtered


def _to_int(raw: str) -> Optional[int]:
    txt = (raw or "").strip()
    if not txt:
        return None
    digits = re.sub(r"[^\d]", "", txt)
    if not digits:
        return None
    try:
        return int(digits)
    except ValueError:
        return None


def search_catalog(
    query: str,
    source_type: str = "all",
    limit: int = 10,
    offset: int = 0,
    db_path: Optional[str] = None,
) -> Dict[str, object]:
    """Search chats/channels by title/link/username/description."""
    q = (query or "").strip()
    if not q:
        return {"query": query, "total": 0, "limit": limit, "offset": offset, "items": []}

    source_type = (source_type or "all").strip().lower()
    limit = max(1, min(int(limit), 50))
    offset = max(0, int(offset))

    username = _normalize_username(q)
    q_lower = q.lower()
    like = f"%{q_lower}%"
    user_like = f"%{username}%" if username else ""

    query_parts = ["(lower(title) LIKE ? OR lower(link) LIKE ? OR lower(description) LIKE ?)"]
    params: List[object] = [like, like, like]

    if username:
        query_parts.append("(lower(username) = ? OR lower(username) LIKE ? OR lower(link) LIKE ?)")
        params.extend([username, user_like, f"%/{username}%"])

    where_sql = "(" + " OR ".join(query_parts) + ")"
    if source_type in {"chat", "channel"}:
        where_sql += " AND source_type = ?"
        params.append(source_type)

    conn = _connect(db_path)
    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) FROM tg_catalog WHERE {where_sql}", params)
    total = int(cur.fetchone()[0])

    cur.execute(
        f"""
        SELECT id, source_type, title, link, username, members, comments_mode,
               can_write, members_list_mode, forum_mode, description
        FROM tg_catalog
        WHERE {where_sql}
        ORDER BY members DESC, id ASC
        LIMIT ? OFFSET ?
        """,
        params + [limit, offset],
    )
    items = [dict(row) for row in cur.fetchall()]
    conn.close()

    return {
        "query": query,
        "normalized_username": username or None,
        "source_type": source_type,
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": items,
    }


def catalog_stats(db_path: Optional[str] = None) -> Dict[str, int]:
    conn = _connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM tg_catalog")
    total = int(cur.fetchone()[0])
    cur.execute("SELECT COUNT(*) FROM tg_catalog WHERE source_type = 'channel'")
    channels = int(cur.fetchone()[0])
    cur.execute("SELECT COUNT(*) FROM tg_catalog WHERE source_type = 'chat'")
    chats = int(cur.fetchone()[0])
    conn.close()
    return {"total": total, "channels": channels, "chats": chats}


def top_catalog(source_type: str = "all", limit: int = 10, db_path: Optional[str] = None) -> List[Dict[str, object]]:
    source_type = (source_type or "all").strip().lower()
    limit = max(1, min(int(limit), 50))
    conn = _connect(db_path)
    cur = conn.cursor()

    if source_type in {"chat", "channel"}:
        cur.execute(
            """
            SELECT id, source_type, title, link, username, members, comments_mode,
                   can_write, members_list_mode, forum_mode, description
            FROM tg_catalog
            WHERE source_type = ?
            ORDER BY members DESC, id ASC
            LIMIT ?
            """,
            (source_type, limit),
        )
    else:
        cur.execute(
            """
            SELECT id, source_type, title, link, username, members, comments_mode,
                   can_write, members_list_mode, forum_mode, description
            FROM tg_catalog
            ORDER BY members DESC, id ASC
            LIMIT ?
            """,
            (limit,),
        )

    items = [dict(row) for row in cur.fetchall()]
    conn.close()
    return items


def random_catalog(source_type: str = "all", db_path: Optional[str] = None) -> Optional[Dict[str, object]]:
    source_type = (source_type or "all").strip().lower()
    conn = _connect(db_path)
    cur = conn.cursor()

    if source_type in {"chat", "channel"}:
        cur.execute(
            """
            SELECT id, source_type, title, link, username, members, comments_mode,
                   can_write, members_list_mode, forum_mode, description
            FROM tg_catalog
            WHERE source_type = ?
            ORDER BY RANDOM()
            LIMIT 1
            """,
            (source_type,),
        )
    else:
        cur.execute(
            """
            SELECT id, source_type, title, link, username, members, comments_mode,
                   can_write, members_list_mode, forum_mode, description
            FROM tg_catalog
            ORDER BY RANDOM()
            LIMIT 1
            """
        )

    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def replace_all_rows(rows: Iterable[Dict[str, object]], db_path: str = DEFAULT_DB_PATH) -> int:
    """Replace entire catalog with provided rows. Returns inserted count."""
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("DELETE FROM tg_catalog")
    payload: List[Tuple[object, ...]] = []

    for row in rows:
        payload.append(
            (
                row.get("source_type"),
                row.get("title"),
                row.get("link"),
                row.get("username"),
                row.get("members"),
                row.get("comments_mode"),
                row.get("can_write"),
                row.get("members_list_mode"),
                row.get("forum_mode"),
                row.get("description"),
            )
        )

    cur.executemany(
        """
        INSERT INTO tg_catalog (
            source_type, title, link, username, members, comments_mode,
            can_write, members_list_mode, forum_mode, description
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        payload,
    )
    conn.commit()
    conn.close()
    return len(payload)


def _col_to_idx(col: str) -> int:
    n = 0
    for ch in col:
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def _parse_shared_strings(z: zipfile.ZipFile) -> List[str]:
    if "xl/sharedStrings.xml" not in z.namelist():
        return []
    root = ET.fromstring(z.read("xl/sharedStrings.xml"))
    values: List[str] = []
    for si in root.findall("a:si", _NS):
        t = si.find("a:t", _NS)
        if t is not None:
            values.append(t.text or "")
            continue
        parts: List[str] = []
        for rr in si.findall("a:r", _NS):
            tt = rr.find("a:t", _NS)
            if tt is not None:
                parts.append(tt.text or "")
        values.append("".join(parts))
    return values


def _first_sheet_path(z: zipfile.ZipFile) -> str:
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    sheets = wb.find("a:sheets", _NS)
    if sheets is None:
        return "xl/worksheets/sheet1.xml"
    first = sheets.find("a:sheet", _NS)
    if first is None:
        return "xl/worksheets/sheet1.xml"
    rid = first.attrib.get("{%s}id" % _NS["r"], "")

    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    target = ""
    for rel in rels:
        if rel.attrib.get("Id") == rid:
            target = rel.attrib.get("Target", "")
            break

    if not target:
        return "xl/worksheets/sheet1.xml"
    if target.startswith("/"):
        target = target[1:]
    if not target.startswith("xl/"):
        target = "xl/" + target
    return target


def _iter_sheet_rows(xlsx_path: str) -> Iterable[List[str]]:
    with zipfile.ZipFile(xlsx_path, "r") as z:
        shared = _parse_shared_strings(z)
        sheet_path = _first_sheet_path(z)
        root = ET.fromstring(z.read(sheet_path))

        for row in root.findall(".//a:sheetData/a:row", _NS):
            values: Dict[int, str] = {}
            max_idx = 0
            for cc in row.findall("a:c", _NS):
                ref = cc.attrib.get("r", "A1")
                mm = re.match(r"([A-Z]+)", ref)
                idx = _col_to_idx(mm.group(1)) if mm else 0
                max_idx = max(max_idx, idx)

                tt = cc.attrib.get("t")
                vv = cc.find("a:v", _NS)
                text = ""
                if tt == "s" and vv is not None and vv.text is not None:
                    try:
                        text = shared[int(vv.text)]
                    except (ValueError, IndexError):
                        text = vv.text
                elif tt == "inlineStr":
                    inline = cc.find("a:is/a:t", _NS)
                    text = inline.text if inline is not None and inline.text is not None else ""
                elif vv is not None and vv.text is not None:
                    text = vv.text
                values[idx] = text

            yield [values.get(i, "").strip() for i in range(max_idx + 1)]


def rows_from_xlsx(
    channels_xlsx_path: str,
    chats_xlsx_path: str,
) -> List[Dict[str, object]]:
    """Build normalized rows from two Telegram catalogs."""
    rows: List[Dict[str, object]] = []

    # Channels file: Название | Ссылка | Участники | Комментарии | Описание
    for rr in _iter_sheet_rows(channels_xlsx_path):
        if len(rr) < 2:
            continue
        title = (rr[0] or "").strip()
        link = (rr[1] or "").strip()

        if not title or not link:
            continue
        if title.lower() in {"каналы", "название"}:
            continue

        rows.append(
            {
                "source_type": "channel",
                "title": title,
                "link": link,
                "username": _normalize_username(link),
                "members": _to_int(rr[2] if len(rr) > 2 else ""),
                "comments_mode": rr[3] if len(rr) > 3 else "",
                "can_write": "",
                "members_list_mode": "",
                "forum_mode": "",
                "description": rr[4] if len(rr) > 4 else "",
            }
        )

    # Chats file: Название | Ссылка | Участники | Можно писать | Список участников | Форум | Описание
    for rr in _iter_sheet_rows(chats_xlsx_path):
        if len(rr) < 2:
            continue
        title = (rr[0] or "").strip()
        link = (rr[1] or "").strip()

        if not title or not link:
            continue
        if title.lower() in {"чаты", "название"}:
            continue

        rows.append(
            {
                "source_type": "chat",
                "title": title,
                "link": link,
                "username": _normalize_username(link),
                "members": _to_int(rr[2] if len(rr) > 2 else ""),
                "comments_mode": "",
                "can_write": rr[3] if len(rr) > 3 else "",
                "members_list_mode": rr[4] if len(rr) > 4 else "",
                "forum_mode": rr[5] if len(rr) > 5 else "",
                "description": rr[6] if len(rr) > 6 else "",
            }
        )

    return rows
