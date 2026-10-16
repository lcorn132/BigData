"""Tạo lớp catalog trình diễn ổn định từ thuộc tính thật trong dataset.

Dataset gốc không có tên, mô tả, ảnh, rating hay số lượt đánh giá. Các trường
trình diễn được sinh xác định theo product_id, lưu riêng và không ghi đè brand,
category hoặc price gốc.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path


BRANDS = (
    "Lunera", "Miora", "Veloura", "Auréne", "Natura Lab", "Élan Skin",
    "Orphée", "Bloom & Co.", "Maison Lune", "Serein Beauty",
)

PRODUCTS = (
    ("serum", "Tinh chất", ("Hyaluronic", "Niacinamide", "Ceramide", "Vitamin C", "Peptide")),
    ("cream", "Kem dưỡng", ("Phục hồi", "Cấp ẩm", "Làm dịu", "Sáng da", "Đêm chuyên sâu")),
    ("cleanser", "Sữa rửa mặt", ("Amino dịu nhẹ", "Trà xanh", "Cân bằng ẩm", "Rau má", "Hoa cúc")),
    ("lipstick", "Son môi", ("Velvet Rose", "Nude Silk", "Coral Muse", "Ruby Bloom", "Berry Cloud")),
    ("mascara", "Mascara", ("Dài mi", "Cong mi", "Chống trôi", "Đen tự nhiên", "Volume Plus")),
    ("palette", "Bảng màu mắt", ("Soft Nude", "Rose Garden", "Warm Earth", "Moonlight", "Daily Muse")),
    ("sunscreen", "Kem chống nắng", ("Aqua SPF50+", "Tone Up SPF50+", "Daily Shield", "Cica Sun", "UV Essence")),
    ("toner", "Nước cân bằng", ("Hydra Calm", "Cica Relief", "Pure Balance", "Rice Glow", "BHA Mild")),
    ("perfume", "Nước hoa", ("White Tea", "Velvet Bloom", "Morning Dew", "Amber Muse", "Soft Peony")),
    ("handcream", "Kem dưỡng tay", ("Shea Butter", "Cotton Bloom", "Rose Tea", "Citrus Herb", "Vanilla Musk")),
    ("shampoo", "Dầu gội", ("Hair Repair", "Scalp Balance", "Silky Moist", "Herbal Fresh", "Volume Care")),
    ("nail", "Sơn móng", ("Rose Petal", "Mocha Nude", "Cherry Wine", "Milk Tea", "Olive Mist")),
)


def product_index(category_code: str | None, digest: bytes) -> int:
    value = (category_code or "").lower()
    rules = {
        "lip": 3, "eye": 5, "nail": 11, "perfume": 8,
        "hair": 10, "clean": 2, "sun": 6, "cream": 1,
    }
    for token, index in rules.items():
        if token in value:
            return index
    return digest[0] % len(PRODUCTS)


def generated_values(product_id: str, brand: str | None, category_code: str | None) -> tuple:
    digest = hashlib.sha256(product_id.encode("utf-8")).digest()
    image_key, type_label, variants = PRODUCTS[product_index(category_code, digest)]
    display_brand = brand.strip() if brand and brand.strip() else BRANDS[digest[1] % len(BRANDS)]
    variant = variants[digest[2] % len(variants)]
    display_name = f"{type_label} {variant}"
    description = (
        f"{display_name} thuộc bộ sưu tập {display_brand}. Nội dung mô tả được "
        "tạo cho giao diện demo và liên kết ổn định với product_id gốc."
    )
    rating = round(4.0 + (digest[3] % 10) / 10, 1)
    review_count = 18 + int.from_bytes(digest[4:6], "big") % 2483
    badge = ("Bán chạy", "Mới", "Được yêu thích", "Lựa chọn tốt", "")[(digest[6] % 5)]
    return display_brand, display_name, type_label, description, image_key, rating, review_count, badge


def enrich_database(database: Path) -> int:
    if not database.is_file():
        raise FileNotFoundError(f"Không tìm thấy SQLite database: {database}")
    connection = sqlite3.connect(database)
    try:
        existing = {row[1] for row in connection.execute("PRAGMA table_info(product_catalog)")}
        columns = {
            "display_brand": "TEXT", "display_name": "TEXT", "product_type": "TEXT",
            "description": "TEXT", "image_key": "TEXT", "demo_rating": "REAL",
            "demo_review_count": "INTEGER", "demo_badge": "TEXT",
            "enrichment_source": "TEXT",
        }
        for name, dtype in columns.items():
            if name not in existing:
                connection.execute(f"ALTER TABLE product_catalog ADD COLUMN {name} {dtype}")

        rows = connection.execute(
            "SELECT product_id, brand, category_code FROM product_catalog"
        ).fetchall()
        updates = []
        for product_id, brand, category_code in rows:
            values = generated_values(str(product_id), brand, category_code)
            updates.append((*values, "generated_for_demo", str(product_id)))
        connection.executemany(
            """
            UPDATE product_catalog SET
              display_brand=?, display_name=?, product_type=?, description=?,
              image_key=?, demo_rating=?, demo_review_count=?, demo_badge=?,
              enrichment_source=? WHERE product_id=?
            """,
            updates,
        )
        connection.execute("CREATE INDEX IF NOT EXISTS idx_products_display_name ON product_catalog(display_name)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_products_display_brand ON product_catalog(display_brand)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_products_type ON product_catalog(product_type)")
        payload = json.dumps({
            "status": "ready",
            "row_count": len(rows),
            "source": "generated_for_demo",
            "notice": "Tên, mô tả, rating, review và hình minh họa được sinh xác định; ID, brand gốc, category và price lấy từ dataset.",
        }, ensure_ascii=False)
        connection.execute(
            "INSERT OR REPLACE INTO app_documents(key, payload) VALUES('catalog_enrichment', ?)",
            (payload,),
        )
        connection.commit()
        return len(rows)
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path("data/cosmetics.db"))
    args = parser.parse_args()
    count = enrich_database(args.database.resolve())
    print(f"Enriched {count:,} products for the demo storefront")


if __name__ == "__main__":
    main()
