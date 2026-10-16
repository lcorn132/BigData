"""Import a serving_export directory or ZIP into SQLite or MongoDB.

Examples:
  python import_data.py --backend sqlite --input serving_export.zip \
      --database data/cosmetics.db --reset

  python import_data.py --backend mongodb --input serving_export.zip \
      --reset --max-users 5000

MongoDB mode reads MONGODB_URI and MONGODB_DATABASE from the environment.
``--max-users`` creates a smaller online demo while the offline SQLite database
can retain the full export.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any, BinaryIO

from pymongo import ASCENDING, MongoClient, ReplaceOne


DATASETS = ("product_catalog", "popular_products", "recommendations", "user_history")
DOCUMENTS = {
    "metadata.json": "metadata",
    "dashboard_stats.json": "dashboard_stats",
    "evaluation_report.json": "evaluation_report",
}


class ExportReader:
    def __init__(self, source: Path):
        self.source = source.resolve()
        self.archive: zipfile.ZipFile | None = None
        if self.source.is_file() and zipfile.is_zipfile(self.source):
            self.archive = zipfile.ZipFile(self.source)
        elif not self.source.is_dir():
            raise FileNotFoundError(f"Input must be a serving_export directory or ZIP: {self.source}")

    def close(self) -> None:
        if self.archive is not None:
            self.archive.close()

    def _dataset_files(self, name: str) -> list[str | Path]:
        marker = f"/{name}/jsonl/"
        if self.archive is not None:
            return sorted(
                info.filename
                for info in self.archive.infolist()
                if not info.is_dir()
                and info.filename.endswith(".json")
                and (marker in f"/{info.filename}" or f"/{name}/" in f"/{info.filename}")
                and Path(info.filename).name.startswith("part-")
            )
        preferred = list(self.source.rglob(f"{name}/jsonl/part-*.json"))
        return sorted(preferred or list(self.source.rglob(f"{name}/**/part-*.json")))

    def _open(self, entry: str | Path) -> BinaryIO:
        if self.archive is not None:
            return self.archive.open(str(entry), "r")
        return Path(entry).open("rb")

    def rows(self, name: str) -> Iterator[dict[str, Any]]:
        files = self._dataset_files(name)
        if not files:
            raise FileNotFoundError(f"No JSONL part files found for {name}")
        for entry in files:
            with self._open(entry) as source:
                for line_number, raw_line in enumerate(source, start=1):
                    if not raw_line.strip():
                        continue
                    try:
                        value = json.loads(raw_line)
                    except json.JSONDecodeError as exc:
                        raise ValueError(f"Invalid JSON in {entry} at line {line_number}") from exc
                    if not isinstance(value, dict):
                        raise ValueError(f"Expected JSON object in {entry} at line {line_number}")
                    yield value

    def document(self, filename: str) -> dict[str, Any]:
        if self.archive is not None:
            matches = [
                info.filename for info in self.archive.infolist()
                if not info.is_dir() and Path(info.filename).name == filename
            ]
            if not matches:
                raise FileNotFoundError(f"Missing {filename} in export ZIP")
            with self.archive.open(sorted(matches, key=lambda name: (name.count("/"), len(name)))[0]) as source:
                return json.load(source)
        matches = list(self.source.rglob(filename))
        if not matches:
            raise FileNotFoundError(f"Missing {filename} in export directory")
        with sorted(matches, key=lambda path: (len(path.parts), len(str(path))))[0].open("r", encoding="utf-8") as source:
            return json.load(source)


def normalize(name: str, row: dict[str, Any]) -> dict[str, Any]:
    result = dict(row)
    for field in ("user_id", "product_id", "category_id"):
        if field in result and result[field] is not None:
            result[field] = str(result[field])
    if name == "recommendations":
        return {key: result.get(key) for key in ("user_id", "product_id", "rank", "als_score")}
    if name == "product_catalog":
        return {key: result.get(key) for key in ("product_id", "brand", "category_id", "category_code", "price")}
    if name == "popular_products":
        return {key: result.get(key) for key in ("rank", "product_id", "item_idx", "distinct_users")}
    if name == "user_history":
        return {key: result.get(key) for key in ("user_id", "product_id", "view_count", "cart_count", "purchase_count")}
    raise ValueError(f"Unknown dataset: {name}")


def selected_rows(
    reader: ExportReader,
    name: str,
    selected_users: set[str] | None,
    max_users: int,
) -> Iterator[dict[str, Any]]:
    for raw in reader.rows(name):
        row = normalize(name, raw)
        if name == "recommendations" and max_users:
            user_id = str(row["user_id"])
            if user_id not in selected_users and len(selected_users) >= max_users:
                continue
            selected_users.add(user_id)
        if name == "user_history" and max_users and str(row["user_id"]) not in selected_users:
            continue
        yield row


SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS recommendations (
  user_id TEXT NOT NULL, product_id TEXT NOT NULL, rank INTEGER NOT NULL,
  als_score REAL, PRIMARY KEY (user_id, rank)
);
CREATE TABLE IF NOT EXISTS product_catalog (
  product_id TEXT PRIMARY KEY, brand TEXT, category_id TEXT,
  category_code TEXT, price REAL
);
CREATE TABLE IF NOT EXISTS popular_products (
  rank INTEGER PRIMARY KEY, product_id TEXT NOT NULL,
  item_idx INTEGER, distinct_users INTEGER
);
CREATE TABLE IF NOT EXISTS user_history (
  user_id TEXT NOT NULL, product_id TEXT NOT NULL,
  view_count INTEGER NOT NULL DEFAULT 0,
  cart_count INTEGER NOT NULL DEFAULT 0,
  purchase_count INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (user_id, product_id)
);
CREATE TABLE IF NOT EXISTS app_documents (
  key TEXT PRIMARY KEY, payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_recommendations_user ON recommendations(user_id, rank);
CREATE INDEX IF NOT EXISTS idx_products_brand ON product_catalog(brand);
CREATE INDEX IF NOT EXISTS idx_products_category ON product_catalog(category_id);
CREATE INDEX IF NOT EXISTS idx_history_user ON user_history(user_id);
"""


SQLITE_INSERTS = {
    "recommendations": "INSERT OR REPLACE INTO recommendations(user_id, product_id, rank, als_score) VALUES(?,?,?,?)",
    "product_catalog": "INSERT OR REPLACE INTO product_catalog(product_id, brand, category_id, category_code, price) VALUES(?,?,?,?,?)",
    "popular_products": "INSERT OR REPLACE INTO popular_products(rank, product_id, item_idx, distinct_users) VALUES(?,?,?,?)",
    "user_history": "INSERT OR REPLACE INTO user_history(user_id, product_id, view_count, cart_count, purchase_count) VALUES(?,?,?,?,?)",
}


SQLITE_FIELDS = {
    "recommendations": ("user_id", "product_id", "rank", "als_score"),
    "product_catalog": ("product_id", "brand", "category_id", "category_code", "price"),
    "popular_products": ("rank", "product_id", "item_idx", "distinct_users"),
    "user_history": ("user_id", "product_id", "view_count", "cart_count", "purchase_count"),
}


def import_sqlite(reader: ExportReader, database: Path, reset: bool, max_users: int, batch_size: int) -> dict[str, int]:
    database.parent.mkdir(parents=True, exist_ok=True)
    if reset and database.exists():
        database.unlink()
    connection = sqlite3.connect(database)
    selected_users: set[str] = set()
    counts: dict[str, int] = {}
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        connection.executescript(SQLITE_SCHEMA)
        for name in DATASETS:
            batch: list[tuple[Any, ...]] = []
            imported = 0
            fields = SQLITE_FIELDS[name]
            for row in selected_rows(reader, name, selected_users, max_users):
                batch.append(tuple(row.get(field) for field in fields))
                if len(batch) >= batch_size:
                    connection.executemany(SQLITE_INSERTS[name], batch)
                    imported += len(batch)
                    connection.commit()
                    batch.clear()
            if batch:
                connection.executemany(SQLITE_INSERTS[name], batch)
                imported += len(batch)
                connection.commit()
            counts[name] = imported
            print(f"Imported {imported:,} rows into SQLite {name}")
        for filename, key in DOCUMENTS.items():
            payload = json.dumps(reader.document(filename), ensure_ascii=False, separators=(",", ":"))
            connection.execute("INSERT OR REPLACE INTO app_documents(key, payload) VALUES(?, ?)", (key, payload))
        connection.commit()
    finally:
        connection.close()
    return counts


MONGO_KEYS = {
    "recommendations": ("user_id", "rank"),
    "product_catalog": ("product_id",),
    "popular_products": ("rank",),
    "user_history": ("user_id", "product_id"),
}


def import_mongodb(reader: ExportReader, reset: bool, max_users: int, batch_size: int) -> dict[str, int]:
    uri = os.getenv("MONGODB_URI")
    if not uri:
        raise RuntimeError("MONGODB_URI must be set for MongoDB import")
    database_name = os.getenv("MONGODB_DATABASE", "cosmetics_recommendation")
    client = MongoClient(uri, serverSelectionTimeoutMS=10000)
    selected_users: set[str] = set()
    counts: dict[str, int] = {}
    try:
        client.admin.command("ping")
        db = client[database_name]
        if reset:
            for name in (*DATASETS, "app_documents"):
                db[name].drop()
        for name in DATASETS:
            collection = db[name]
            keys = MONGO_KEYS[name]
            collection.create_index([(key, ASCENDING) for key in keys], unique=True)
            batch: list[ReplaceOne] = []
            imported = 0
            for row in selected_rows(reader, name, selected_users, max_users):
                selector = {key: row[key] for key in keys}
                batch.append(ReplaceOne(selector, row, upsert=True))
                if len(batch) >= batch_size:
                    collection.bulk_write(batch, ordered=False)
                    imported += len(batch)
                    batch.clear()
            if batch:
                collection.bulk_write(batch, ordered=False)
                imported += len(batch)
            counts[name] = imported
            print(f"Imported/upserted {imported:,} rows into MongoDB {name}")
        docs = db["app_documents"]
        docs.create_index("key", unique=True)
        for filename, key in DOCUMENTS.items():
            docs.replace_one({"key": key}, {"key": key, "payload": reader.document(filename)}, upsert=True)
    finally:
        client.close()
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=("sqlite", "mongodb"), required=True)
    parser.add_argument("--input", type=Path, required=True, help="serving_export directory or ZIP")
    parser.add_argument("--database", type=Path, default=Path("data/cosmetics.db"), help="SQLite output path")
    parser.add_argument("--batch-size", type=int, default=2000)
    parser.add_argument("--max-users", type=int, default=0, help="0 imports all users; set a limit for an online demo")
    parser.add_argument("--reset", action="store_true", help="replace the target database/collections")
    args = parser.parse_args()
    if args.batch_size < 1 or args.max_users < 0:
        parser.error("batch-size must be positive and max-users must be non-negative")

    reader = ExportReader(args.input)
    try:
        if args.backend == "sqlite":
            counts = import_sqlite(reader, args.database.resolve(), args.reset, args.max_users, args.batch_size)
        else:
            counts = import_mongodb(reader, args.reset, args.max_users, args.batch_size)
    finally:
        reader.close()
    print("Import completed:", json.dumps(counts, ensure_ascii=False))


if __name__ == "__main__":
    main()
