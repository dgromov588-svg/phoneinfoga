"""Directory database utilities for importing organization records from CSV.

Data source: user's own data with consent for processing.
Stores full rows (all fields) and a few parsed columns for convenience.
"""

from __future__ import annotations

import csv
import json
import os
import sqlite3
from datetime import datetime
from typing import Iterable, List, Optional, Tuple


DEFAULT_DB_PATH = "business_directory.db"


def get_db_path() -> str:
    return os.getenv("DIRECTORY_DB_PATH", DEFAULT_DB_PATH)


def init_db(db_path: str = DEFAULT_DB_PATH) -> None:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS datasets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            source_file TEXT UNIQUE,
            city TEXT,
            header_json TEXT,
            encoding TEXT,
            imported_at TEXT
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dataset_id INTEGER,
            oid TEXT,
            name TEXT,
            legal_form TEXT,
            category TEXT,
            subcategory TEXT,
            services TEXT,
            description TEXT,
            phones TEXT,
            email TEXT,
            site TEXT,
            address TEXT,
            postal_code TEXT,
            hours TEXT,
            extra_1 TEXT,
            extra_2 TEXT,
            extra_3 TEXT,
            vk TEXT,
            facebook TEXT,
            skype TEXT,
            twitter TEXT,
            instagram TEXT,
            icq TEXT,
            jabber TEXT,
            raw_json TEXT,
            FOREIGN KEY(dataset_id) REFERENCES datasets(id)
        )
        """
    )

    conn.commit()
    conn.close()


def _detect_encoding(file_path: str) -> str:
    """Best-effort encoding detection for CSV files."""
    for enc in ("utf-8", "cp1251", "latin-1"):
        try:
            with open(file_path, "r", encoding=enc) as f:
                f.readline()
            return enc
        except UnicodeDecodeError:
            continue
    return "latin-1"


def _city_from_filename(file_path: str) -> str:
    base = os.path.basename(file_path)
    name = os.path.splitext(base)[0]
    # Example: Data_Abakan -> Abakan
    if name.lower().startswith("data_"):
        return name.split("_", 1)[1]
    return name


def _normalize_row(row: List[str], width: int) -> List[str]:
    if len(row) < width:
        row = row + [""] * (width - len(row))
    return [col.strip() for col in row[:width]]


def import_csv(
    file_path: str,
    db_path: str = DEFAULT_DB_PATH,
    dataset_name: Optional[str] = None,
) -> Tuple[int, int]:
    """Import a single CSV file. Returns (dataset_id, records_added)."""
    init_db(db_path)

    encoding = _detect_encoding(file_path)
    with open(file_path, "r", encoding=encoding, newline="") as f:
        reader = csv.reader(f, delimiter=";")
        try:
            header = next(reader)
        except StopIteration:
            return (0, 0)

        header = _normalize_row(header, len(header))
        width = len(header)

        rows = [_normalize_row(row, width) for row in reader if any(cell.strip() for cell in row)]

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    source_file = os.path.abspath(file_path)
    city = _city_from_filename(file_path)
    name = dataset_name or city

    # Insert dataset if not already imported
    cursor.execute("SELECT id FROM datasets WHERE source_file = ?", (source_file,))
    existing = cursor.fetchone()
    if existing:
        dataset_id = existing[0]
        conn.close()
        return (dataset_id, 0)

    cursor.execute(
        """
        INSERT INTO datasets (name, source_file, city, header_json, encoding, imported_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            name,
            source_file,
            city,
            json.dumps(header, ensure_ascii=False),
            encoding,
            datetime.now().isoformat(),
        ),
    )
    dataset_id = cursor.lastrowid

    # Map common columns by index
    def col(i: int) -> str:
        return rows_col[i] if i < len(rows_col) else ""

    records_to_insert = []
    for rows_col in rows:
        raw_json = json.dumps(rows_col, ensure_ascii=False)
        records_to_insert.append(
            (
                dataset_id,
                col(0),  # oid
                col(1),  # name
                col(2),  # legal_form
                col(3),  # category
                col(4),  # subcategory
                col(5),  # services
                col(6),  # description/extra
                col(7),  # phones
                col(8),  # email
                col(9),  # site
                col(10),  # address
                col(11),  # postal_code
                col(12),  # hours
                col(13),  # extra_1
                col(14),  # extra_2
                col(15),  # extra_3
                col(16),  # vk
                col(17),  # facebook
                col(18),  # skype
                col(19),  # twitter
                col(20),  # instagram
                col(21),  # icq
                col(22),  # jabber
                raw_json,
            )
        )

    cursor.executemany(
        """
        INSERT INTO records (
            dataset_id, oid, name, legal_form, category, subcategory, services, description,
            phones, email, site, address, postal_code, hours, extra_1, extra_2, extra_3,
            vk, facebook, skype, twitter, instagram, icq, jabber, raw_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        records_to_insert,
    )

    conn.commit()
    conn.close()
    return (dataset_id, len(records_to_insert))


def import_many(file_paths: Iterable[str], db_path: str = DEFAULT_DB_PATH) -> List[Tuple[str, int]]:
    results = []
    for path in file_paths:
        _, count = import_csv(path, db_path=db_path)
        results.append((path, count))
    return results


def _normalize_phone_value(value: str) -> str:
    return "".join(ch for ch in value if ch.isdigit() or ch == "+")


def _connect(db_path: Optional[str] = None) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path or get_db_path())
    conn.row_factory = sqlite3.Row
    return conn


def search_records(
    query: str,
    field: str = "all",
    limit: int = 50,
    offset: int = 0,
    db_path: Optional[str] = None,
) -> dict:
    """Search records by phone/name/address (or across all)."""
    query = (query or "").strip()
    if not query:
        return {"total": 0, "limit": limit, "offset": offset, "items": []}

    field = (field or "all").lower()
    limit = max(1, min(int(limit), 500))
    offset = max(0, int(offset))

    like = f"%{query}%"
    phone_like = f"%{_normalize_phone_value(query)}%"

    where = ""
    params: List[str] = []
    if field == "phone":
        where = "(r.phones LIKE ? OR r.phones LIKE ?)"
        params = [like, phone_like]
    elif field == "name":
        where = "(r.name LIKE ?)"
        params = [like]
    elif field == "address":
        where = "(r.address LIKE ?)"
        params = [like]
    else:
        where = "(r.name LIKE ? OR r.phones LIKE ? OR r.address LIKE ? OR r.email LIKE ? OR r.site LIKE ?)"
        params = [like, phone_like, like, like, like]

    conn = _connect(db_path)
    cursor = conn.cursor()

    cursor.execute(
        f"""
        SELECT COUNT(*) AS cnt
        FROM records r
        LEFT JOIN datasets d ON d.id = r.dataset_id
        WHERE {where}
        """,
        params,
    )
    total = int(cursor.fetchone()[0])

    cursor.execute(
        f"""
        SELECT r.*, d.city AS city, d.name AS dataset_name
        FROM records r
        LEFT JOIN datasets d ON d.id = r.dataset_id
        WHERE {where}
        ORDER BY r.id DESC
        LIMIT ? OFFSET ?
        """,
        params + [limit, offset],
    )

    items = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return {"total": total, "limit": limit, "offset": offset, "items": items}


def stats_by_city_and_category(db_path: Optional[str] = None, top_n: int = 20) -> dict:
    """Return counts by city and category."""
    top_n = max(1, min(int(top_n), 200))
    conn = _connect(db_path)
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) AS cnt FROM records")
    total = int(cursor.fetchone()[0])

    cursor.execute(
        """
        SELECT d.city AS city, COUNT(*) AS cnt
        FROM records r
        LEFT JOIN datasets d ON d.id = r.dataset_id
        GROUP BY d.city
        ORDER BY cnt DESC
        LIMIT ?
        """,
        (top_n,),
    )
    by_city = [{"city": row[0], "count": row[1]} for row in cursor.fetchall()]

    cursor.execute(
        """
        SELECT r.category AS category, COUNT(*) AS cnt
        FROM records r
        GROUP BY r.category
        ORDER BY cnt DESC
        LIMIT ?
        """,
        (top_n,),
    )
    by_category = [{"category": row[0], "count": row[1]} for row in cursor.fetchall()]

    conn.close()
    return {"total": total, "top_n": top_n, "by_city": by_city, "by_category": by_category}
