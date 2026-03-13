#!/usr/bin/env python3
"""Import Telegram channels/chats XLSX catalogs into SQLite DB."""

from __future__ import annotations

import argparse
import os

from tg_catalog_db import replace_all_rows, rows_from_xlsx


def main() -> int:
    parser = argparse.ArgumentParser(description="Import Telegram chat/channel XLSX catalogs")
    parser.add_argument("--channels", required=True, help="Path to channels XLSX")
    parser.add_argument("--chats", required=True, help="Path to chats XLSX")
    parser.add_argument("--db", default="tg_catalog.db", help="Output SQLite DB path")
    args = parser.parse_args()

    channels_path = os.path.abspath(args.channels)
    chats_path = os.path.abspath(args.chats)
    db_path = os.path.abspath(args.db)

    rows = rows_from_xlsx(channels_path, chats_path)
    inserted = replace_all_rows(rows, db_path=db_path)
    print(f"Imported {inserted} rows into {db_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

