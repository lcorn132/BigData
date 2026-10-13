"""Import Spark DataFrame JSON exports into MongoDB Atlas/compatible MongoDB.

Each input is a Spark `.write.json(...)` directory containing part-*.json files.
The input directory should contain subdirectories named after the collections.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Iterator

from pymongo import MongoClient, ReplaceOne


COLLECTION_KEYS = {
    "user_recommendations": "user_id",
    "item_associations": "antecedent_idx",
    "cluster_fallbacks": "cluster_id",
    "product_metadata": "product_id",
}


def iter_documents(directory: Path) -> Iterator[dict]:
    for file_path in sorted(directory.rglob("*.json")):
        with file_path.open("r", encoding="utf-8") as source:
            for line_number, line in enumerate(source, start=1):
                if not line.strip():
                    continue
                try:
                    document = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"Invalid JSON at {file_path}:{line_number}") from exc
                if not isinstance(document, dict):
                    raise ValueError(f"Expected JSON object at {file_path}:{line_number}")
                yield document


def import_collection(db, input_dir: Path, name: str, key: str, batch_size: int) -> int:
    collection_dir = input_dir / name
    if not collection_dir.is_dir():
        raise FileNotFoundError(f"Missing Spark export directory: {collection_dir}")

    collection = db[name]
    collection.create_index(key, unique=True)
    batch = []
    imported = 0

    for document in iter_documents(collection_dir):
        if key not in document:
            raise ValueError(f"Document in {name} is missing key {key!r}")
        batch.append(ReplaceOne({key: document[key]}, document, upsert=True))
        if len(batch) >= batch_size:
            collection.bulk_write(batch, ordered=False)
            imported += len(batch)
            batch.clear()

    if batch:
        collection.bulk_write(batch, ordered=False)
        imported += len(batch)
    return imported


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", required=True, type=Path)
    parser.add_argument("--batch-size", default=1000, type=int)
    args = parser.parse_args()

    mongo_uri = os.getenv("MONGODB_URI")
    database_name = os.getenv("MONGODB_DATABASE", "recommendation_db")
    if not mongo_uri:
        parser.error("Set MONGODB_URI in the environment; do not pass it on the command line")

    client = MongoClient(mongo_uri, serverSelectionTimeoutMS=10000)
    try:
        client.admin.command("ping")
        db = client[database_name]
        for collection_name, key in COLLECTION_KEYS.items():
            count = import_collection(db, args.input_dir, collection_name, key, args.batch_size)
            print(f"Imported/upserted {count:,} documents into {collection_name}")
    finally:
        client.close()


if __name__ == "__main__":
    main()
