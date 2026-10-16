"""Tự đồng bộ serving_export từ HDFS và tạo SQLite cache cho ứng dụng."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from pathlib import Path

from hdfs_sync import HdfsSshClient, state_key
from import_data import ExportReader, import_sqlite


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATABASE = Path(os.getenv("DATABASE_PATH", DATA_DIR / "cosmetics.db")).resolve()
ARCHIVE = DATA_DIR / "serving_export.zip"
STATE_FILE = DATA_DIR / "hdfs_state.json"


def database_ready() -> bool:
    if not DATABASE.is_file():
        return False
    try:
        with sqlite3.connect(DATABASE) as connection:
            return connection.execute(
                "SELECT 1 FROM product_catalog LIMIT 1"
            ).fetchone() is not None
    except sqlite3.Error:
        return False


def read_state() -> dict[str, str]:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="đồng bộ lại dù HDFS chưa đổi")
    args = parser.parse_args()

    client = HdfsSshClient()
    remote_signature = client.signature()
    expected_state = state_key(client, remote_signature)
    if not args.force and database_ready() and read_state() == expected_state:
        print("[HDFS] Dữ liệu không đổi; dùng SQLite cache hiện có.")
        return

    print(f"[HDFS] Đang tải {client.hdfs_path} từ {client.host}...")
    downloaded_signature = client.download(ARCHIVE)
    reader = ExportReader(ARCHIVE)
    try:
        counts = import_sqlite(reader, DATABASE, reset=True, max_users=0, batch_size=5000)
    finally:
        reader.close()
    STATE_FILE.write_text(
        json.dumps(state_key(client, downloaded_signature), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("[HDFS] Đã tạo SQLite cache:", json.dumps(counts, ensure_ascii=False))


if __name__ == "__main__":
    main()
