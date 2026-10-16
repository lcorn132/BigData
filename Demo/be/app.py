"""FastAPI service for the verified cosmetics ALS serving export.

The same source supports SQLite for the offline submission and MongoDB for the
online deployment. Redis is an optional cache. Public APIs always expose the
original user_id and product_id values, never Spark's internal indexes.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field
from pymongo import ASCENDING
from redis.asyncio import Redis


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("cosmetics_recommendation_api")

DATA_BACKEND = os.getenv("DATA_BACKEND", "sqlite").lower()
DATABASE_PATH = Path(os.getenv("DATABASE_PATH", "data/cosmetics.db")).resolve()
MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
MONGODB_DATABASE = os.getenv("MONGODB_DATABASE", "cosmetics_recommendation")
REDIS_URL = os.getenv("REDIS_URL", "").strip()
USE_REDIS = os.getenv("USE_REDIS", "false").lower() in {"1", "true", "yes"}
CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", "3600"))
DB_TIMEOUT_SECONDS = float(os.getenv("DB_TIMEOUT_SECONDS", "5"))
MODEL_NAME = "COUNT_C3"
HDFS_STATE_PATH = DATABASE_PATH.parent / "hdfs_state.json"

COLLECTION_RECOMMENDATIONS = "recommendations"
COLLECTION_PRODUCTS = "product_catalog"
COLLECTION_POPULAR = "popular_products"
COLLECTION_HISTORY = "user_history"
COLLECTION_DOCUMENTS = "app_documents"


class Product(BaseModel):
    product_id: str
    brand: Optional[str] = None
    category_id: Optional[str] = None
    category_code: Optional[str] = None
    price: Optional[float] = None


class RecommendationItem(Product):
    rank: int
    als_score: Optional[float] = None
    distinct_users: Optional[int] = None


class RecommendationResponse(BaseModel):
    user_id: str
    strategy: str
    model: Optional[str] = None
    items: list[RecommendationItem] = Field(default_factory=list)


class ProductPage(BaseModel):
    items: list[Product]
    page: int
    page_size: int
    total: int
    pages: int


class HistoryItem(Product):
    view_count: int = 0
    cart_count: int = 0
    purchase_count: int = 0


class HistoryResponse(BaseModel):
    user_id: str
    items: list[HistoryItem]
    total_products: int


def _string_id(value: Any) -> str:
    return "" if value is None else str(value)


class SQLiteStore:
    def __init__(self, path: Path):
        self.path = path

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    async def ready(self) -> bool:
        def check() -> bool:
            if not self.path.is_file():
                return False
            try:
                with self._connect() as db:
                    return db.execute("SELECT 1 FROM product_catalog LIMIT 1").fetchone() is not None
            except sqlite3.Error:
                return False

        return await asyncio.to_thread(check)

    async def recommendation_rows(self, user_id: str, limit: int) -> list[dict[str, Any]]:
        def query() -> list[dict[str, Any]]:
            with self._connect() as db:
                rows = db.execute(
                    """
                    SELECT r.rank, r.product_id, r.als_score,
                           p.brand, p.category_id, p.category_code, p.price
                    FROM recommendations r
                    LEFT JOIN product_catalog p ON p.product_id = r.product_id
                    WHERE r.user_id = ? ORDER BY r.rank ASC LIMIT ?
                    """,
                    (user_id, limit),
                ).fetchall()
                return [dict(row) for row in rows]

        return await asyncio.to_thread(query)

    async def popular_rows(self, limit: int) -> list[dict[str, Any]]:
        def query() -> list[dict[str, Any]]:
            with self._connect() as db:
                rows = db.execute(
                    """
                    SELECT pp.rank, pp.product_id, pp.distinct_users,
                           p.brand, p.category_id, p.category_code, p.price
                    FROM popular_products pp
                    LEFT JOIN product_catalog p ON p.product_id = pp.product_id
                    ORDER BY pp.rank ASC LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
                return [dict(row) for row in rows]

        return await asyncio.to_thread(query)

    async def products(
        self, q: str, brand: str, category_id: str,
        min_price: Optional[float], max_price: Optional[float],
        page: int, page_size: int,
    ) -> tuple[list[dict[str, Any]], int]:
        def query() -> tuple[list[dict[str, Any]], int]:
            clauses: list[str] = []
            params: list[Any] = []
            if q:
                clauses.append("(product_id LIKE ? OR COALESCE(brand, '') LIKE ? OR COALESCE(category_code, '') LIKE ?)")
                needle = f"%{q}%"
                params.extend([needle, needle, needle])
            if brand:
                clauses.append("brand = ?")
                params.append(brand)
            if category_id:
                clauses.append("category_id = ?")
                params.append(category_id)
            if min_price is not None:
                clauses.append("price >= ?")
                params.append(min_price)
            if max_price is not None:
                clauses.append("price <= ?")
                params.append(max_price)
            where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            with self._connect() as db:
                total = int(db.execute(f"SELECT COUNT(*) FROM product_catalog {where}", params).fetchone()[0])
                rows = db.execute(
                    f"""
                    SELECT product_id, brand, category_id, category_code, price
                    FROM product_catalog {where}
                    ORDER BY CAST(product_id AS INTEGER) LIMIT ? OFFSET ?
                    """,
                    [*params, page_size, (page - 1) * page_size],
                ).fetchall()
                return [dict(row) for row in rows], total

        return await asyncio.to_thread(query)

    async def product(self, product_id: str) -> Optional[dict[str, Any]]:
        def query() -> Optional[dict[str, Any]]:
            with self._connect() as db:
                row = db.execute(
                    "SELECT product_id, brand, category_id, category_code, price FROM product_catalog WHERE product_id = ?",
                    (product_id,),
                ).fetchone()
                return dict(row) if row else None

        return await asyncio.to_thread(query)

    async def filters(self) -> dict[str, list[dict[str, Any]]]:
        def query() -> dict[str, list[dict[str, Any]]]:
            with self._connect() as db:
                brands = db.execute(
                    """SELECT brand AS value, COUNT(*) AS count FROM product_catalog
                    WHERE brand IS NOT NULL AND brand <> '' GROUP BY brand
                    ORDER BY count DESC, brand LIMIT 100"""
                ).fetchall()
                categories = db.execute(
                    """SELECT category_id AS value, COUNT(*) AS count FROM product_catalog
                    WHERE category_id IS NOT NULL AND category_id <> '' GROUP BY category_id
                    ORDER BY count DESC, category_id LIMIT 100"""
                ).fetchall()
                return {"brands": [dict(row) for row in brands], "categories": [dict(row) for row in categories]}

        return await asyncio.to_thread(query)

    async def history(self, user_id: str, limit: int) -> tuple[list[dict[str, Any]], int]:
        def query() -> tuple[list[dict[str, Any]], int]:
            with self._connect() as db:
                total = int(db.execute("SELECT COUNT(*) FROM user_history WHERE user_id = ?", (user_id,)).fetchone()[0])
                rows = db.execute(
                    """
                    SELECT h.product_id, h.view_count, h.cart_count, h.purchase_count,
                           p.brand, p.category_id, p.category_code, p.price
                    FROM user_history h
                    LEFT JOIN product_catalog p ON p.product_id = h.product_id
                    WHERE h.user_id = ?
                    ORDER BY h.purchase_count DESC, h.cart_count DESC,
                             h.view_count DESC, CAST(h.product_id AS INTEGER) LIMIT ?
                    """,
                    (user_id, limit),
                ).fetchall()
                return [dict(row) for row in rows], total

        return await asyncio.to_thread(query)

    async def demo_users(self, limit: int) -> list[str]:
        def query() -> list[str]:
            with self._connect() as db:
                rows = db.execute(
                    "SELECT user_id FROM recommendations GROUP BY user_id ORDER BY CAST(user_id AS INTEGER) LIMIT ?",
                    (limit,),
                ).fetchall()
                return [str(row[0]) for row in rows]

        return await asyncio.to_thread(query)

    async def document(self, key: str) -> Optional[dict[str, Any]]:
        def query() -> Optional[dict[str, Any]]:
            with self._connect() as db:
                row = db.execute("SELECT payload FROM app_documents WHERE key = ?", (key,)).fetchone()
                return json.loads(row[0]) if row else None

        return await asyncio.to_thread(query)


class MongoStore:
    def __init__(self, client: AsyncIOMotorClient, database_name: str):
        self.client = client
        self.db = client[database_name]

    async def create_indexes(self) -> None:
        await self.db[COLLECTION_RECOMMENDATIONS].create_index([("user_id", ASCENDING), ("rank", ASCENDING)], unique=True)
        await self.db[COLLECTION_PRODUCTS].create_index("product_id", unique=True)
        await self.db[COLLECTION_POPULAR].create_index("rank", unique=True)
        await self.db[COLLECTION_HISTORY].create_index([("user_id", ASCENDING), ("product_id", ASCENDING)], unique=True)
        await self.db[COLLECTION_DOCUMENTS].create_index("key", unique=True)

    async def ready(self) -> bool:
        try:
            await asyncio.wait_for(self.db.command("ping"), DB_TIMEOUT_SECONDS)
            return await self.db[COLLECTION_PRODUCTS].estimated_document_count() > 0
        except Exception:
            return False

    async def _catalog(self, product_ids: list[str]) -> dict[str, dict[str, Any]]:
        cursor = self.db[COLLECTION_PRODUCTS].find({"product_id": {"$in": product_ids}}, {"_id": 0})
        return {str(row["product_id"]): row async for row in cursor}

    async def recommendation_rows(self, user_id: str, limit: int) -> list[dict[str, Any]]:
        rows = await self.db[COLLECTION_RECOMMENDATIONS].find({"user_id": user_id}, {"_id": 0}).sort("rank", ASCENDING).limit(limit).to_list(length=limit)
        catalog = await self._catalog([str(row["product_id"]) for row in rows])
        return [{**catalog.get(str(row["product_id"]), {}), **row} for row in rows]

    async def popular_rows(self, limit: int) -> list[dict[str, Any]]:
        rows = await self.db[COLLECTION_POPULAR].find({}, {"_id": 0}).sort("rank", ASCENDING).limit(limit).to_list(length=limit)
        catalog = await self._catalog([str(row["product_id"]) for row in rows])
        return [{**catalog.get(str(row["product_id"]), {}), **row} for row in rows]

    async def products(
        self, q: str, brand: str, category_id: str,
        min_price: Optional[float], max_price: Optional[float],
        page: int, page_size: int,
    ) -> tuple[list[dict[str, Any]], int]:
        query: dict[str, Any] = {}
        if q:
            pattern = re.escape(q)
            query["$or"] = [
                {"product_id": {"$regex": pattern, "$options": "i"}},
                {"brand": {"$regex": pattern, "$options": "i"}},
                {"category_code": {"$regex": pattern, "$options": "i"}},
            ]
        if brand:
            query["brand"] = brand
        if category_id:
            query["category_id"] = category_id
        if min_price is not None or max_price is not None:
            query["price"] = {}
            if min_price is not None:
                query["price"]["$gte"] = min_price
            if max_price is not None:
                query["price"]["$lte"] = max_price
        total = await self.db[COLLECTION_PRODUCTS].count_documents(query)
        rows = await self.db[COLLECTION_PRODUCTS].find(query, {"_id": 0}).sort("product_id", ASCENDING).skip((page - 1) * page_size).limit(page_size).to_list(length=page_size)
        return rows, total

    async def product(self, product_id: str) -> Optional[dict[str, Any]]:
        return await self.db[COLLECTION_PRODUCTS].find_one({"product_id": product_id}, {"_id": 0})

    async def filters(self) -> dict[str, list[dict[str, Any]]]:
        async def values(field: str) -> list[dict[str, Any]]:
            pipeline = [
                {"$match": {field: {"$nin": [None, ""]}}},
                {"$group": {"_id": f"${field}", "count": {"$sum": 1}}},
                {"$sort": {"count": -1, "_id": 1}}, {"$limit": 100},
            ]
            return [{"value": str(row["_id"]), "count": row["count"]} async for row in self.db[COLLECTION_PRODUCTS].aggregate(pipeline)]

        return {"brands": await values("brand"), "categories": await values("category_id")}

    async def history(self, user_id: str, limit: int) -> tuple[list[dict[str, Any]], int]:
        total = await self.db[COLLECTION_HISTORY].count_documents({"user_id": user_id})
        rows = await self.db[COLLECTION_HISTORY].find({"user_id": user_id}, {"_id": 0}).sort([
            ("purchase_count", -1), ("cart_count", -1), ("view_count", -1), ("product_id", ASCENDING),
        ]).limit(limit).to_list(length=limit)
        catalog = await self._catalog([str(row["product_id"]) for row in rows])
        return [{**catalog.get(str(row["product_id"]), {}), **row} for row in rows], total

    async def demo_users(self, limit: int) -> list[str]:
        pipeline = [{"$group": {"_id": "$user_id"}}, {"$sort": {"_id": 1}}, {"$limit": limit}]
        return [str(row["_id"]) async for row in self.db[COLLECTION_RECOMMENDATIONS].aggregate(pipeline)]

    async def document(self, key: str) -> Optional[dict[str, Any]]:
        row = await self.db[COLLECTION_DOCUMENTS].find_one({"key": key}, {"_id": 0})
        return row.get("payload") if row else None


async def _cache_get(redis: Optional[Redis], key: str) -> Optional[dict[str, Any]]:
    if redis is None:
        return None
    try:
        payload = await redis.get(key)
        return json.loads(payload) if payload else None
    except Exception:
        logger.warning("Redis read failed; continuing without cache", exc_info=True)
        return None


async def _cache_set(redis: Optional[Redis], key: str, value: dict[str, Any]) -> None:
    if redis is None:
        return
    try:
        await redis.set(key, json.dumps(value, separators=(",", ":")), ex=CACHE_TTL_SECONDS)
    except Exception:
        logger.warning("Redis write failed; continuing without cache", exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    mongo_client: Optional[AsyncIOMotorClient] = None
    redis_client: Optional[Redis] = None
    if DATA_BACKEND == "mongodb":
        mongo_client = AsyncIOMotorClient(
            MONGODB_URI,
            serverSelectionTimeoutMS=int(DB_TIMEOUT_SECONDS * 1000),
            connectTimeoutMS=int(DB_TIMEOUT_SECONDS * 1000),
            socketTimeoutMS=int(DB_TIMEOUT_SECONDS * 1000),
        )
        store: SQLiteStore | MongoStore = MongoStore(mongo_client, MONGODB_DATABASE)
        await store.create_indexes()
    elif DATA_BACKEND == "sqlite":
        store = SQLiteStore(DATABASE_PATH)
    else:
        raise RuntimeError("DATA_BACKEND must be 'sqlite' or 'mongodb'")
    if USE_REDIS and REDIS_URL:
        redis_client = Redis.from_url(
            REDIS_URL, decode_responses=True,
            socket_connect_timeout=DB_TIMEOUT_SECONDS,
            socket_timeout=DB_TIMEOUT_SECONDS,
        )
    app.state.store = store
    app.state.redis = redis_client
    try:
        yield
    finally:
        if mongo_client is not None:
            mongo_client.close()
        if redis_client is not None:
            await redis_client.aclose()


app = FastAPI(
    title="Cosmetics Behavior & Recommendation API",
    description="Verified COUNT_C3 implicit ALS serving API for HUIT Group 11.",
    version="2.0.0",
    lifespan=lifespan,
)

cors_origins = [origin.strip() for origin in os.getenv(
    "CORS_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000"
).split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware, allow_origins=cors_origins, allow_credentials=False,
    allow_methods=["GET", "OPTIONS"], allow_headers=["*"],
)

WEB_DIR = Path(os.getenv(
    "FRONTEND_DIR", str(Path(__file__).resolve().parent.parent / "fe")
)).resolve()
app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")


@app.get("/", include_in_schema=False)
async def storefront() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/config.js", include_in_schema=False)
async def frontend_config() -> Response:
    return Response("window.RECSYS_API_BASE_URL = '';\n", media_type="text/javascript")


@app.get("/health")
async def health(request: Request) -> dict[str, Any]:
    ready = await request.app.state.store.ready()
    cache = "disabled"
    if request.app.state.redis is not None:
        try:
            await request.app.state.redis.ping()
            cache = "ready"
        except Exception:
            cache = "unavailable"
    return {
        "status": "ok" if ready else "degraded",
        "data_ready": ready,
        "data_backend": DATA_BACKEND,
        "cache": cache,
    }


@app.get("/ready")
async def readiness(request: Request) -> dict[str, str]:
    if not await request.app.state.store.ready():
        raise HTTPException(
            status_code=503,
            detail="Serving data is not loaded. Run Demo/be/setup.bat first.",
        )
    return {"status": "ready"}


def _product(row: dict[str, Any]) -> Product:
    data = dict(row)
    data["product_id"] = _string_id(data.get("product_id"))
    data["category_id"] = _string_id(data.get("category_id")) or None
    return Product(**data)


@app.get("/api/v1/products", response_model=ProductPage)
async def list_products(
    request: Request,
    q: str = Query(default="", max_length=100),
    brand: str = Query(default="", max_length=100),
    category_id: str = Query(default="", max_length=40),
    min_price: Optional[float] = Query(default=None, ge=0),
    max_price: Optional[float] = Query(default=None, ge=0),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=24, ge=1, le=100),
) -> ProductPage:
    if min_price is not None and max_price is not None and min_price > max_price:
        raise HTTPException(status_code=422, detail="min_price must not exceed max_price")
    rows, total = await request.app.state.store.products(
        q.strip(), brand.strip(), category_id.strip(), min_price, max_price, page, page_size
    )
    return ProductPage(
        items=[_product(row) for row in rows], page=page, page_size=page_size,
        total=total, pages=max(1, (total + page_size - 1) // page_size),
    )


@app.get("/api/v1/products/filters")
async def product_filters(request: Request) -> dict[str, Any]:
    return await request.app.state.store.filters()


@app.get("/api/v1/products/{product_id}", response_model=Product)
async def product_detail(product_id: str, request: Request) -> Product:
    row = await request.app.state.store.product(product_id)
    if not row:
        raise HTTPException(status_code=404, detail="Product not found")
    return _product(row)


@app.get("/api/v1/recommendations/{user_id}", response_model=RecommendationResponse)
async def recommendations(
    user_id: str, request: Request,
    limit: int = Query(default=10, ge=1, le=10),
) -> RecommendationResponse:
    cache_key = f"v2:recommendations:{user_id}:{limit}"
    cached = await _cache_get(request.app.state.redis, cache_key)
    if cached:
        return RecommendationResponse(**cached)
    rows = await request.app.state.store.recommendation_rows(user_id, limit)
    strategy, model = "als_count_c3", MODEL_NAME
    if not rows:
        rows = await request.app.state.store.popular_rows(limit)
        strategy, model = "popularity_fallback", None
    items = []
    for row in rows:
        data = dict(row)
        data["product_id"] = _string_id(data.get("product_id"))
        data["category_id"] = _string_id(data.get("category_id")) or None
        items.append(RecommendationItem(**data))
    response = RecommendationResponse(user_id=user_id, strategy=strategy, model=model, items=items)
    await _cache_set(request.app.state.redis, cache_key, response.model_dump())
    return response


@app.get("/api/v1/users/{user_id}/history", response_model=HistoryResponse)
async def user_history(
    user_id: str, request: Request,
    limit: int = Query(default=30, ge=1, le=100),
) -> HistoryResponse:
    rows, total = await request.app.state.store.history(user_id, limit)
    items = []
    for row in rows:
        data = dict(row)
        data["product_id"] = _string_id(data.get("product_id"))
        data["category_id"] = _string_id(data.get("category_id")) or None
        items.append(HistoryItem(**data))
    return HistoryResponse(user_id=user_id, items=items, total_products=total)


@app.get("/api/v1/demo-users")
async def demo_users(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
) -> dict[str, list[str]]:
    return {"users": await request.app.state.store.demo_users(limit)}


@app.get("/api/v1/dashboard")
async def dashboard(request: Request) -> dict[str, Any]:
    stats, evaluation, metadata = await asyncio.gather(
        request.app.state.store.document("dashboard_stats"),
        request.app.state.store.document("evaluation_report"),
        request.app.state.store.document("metadata"),
    )
    hdfs_state: dict[str, Any] = {}
    try:
        hdfs_state = json.loads(HDFS_STATE_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    data_source = {
        "mode": "hdfs_with_sqlite_cache" if hdfs_state else "local_sqlite_cache",
        "hdfs_synced": bool(hdfs_state),
        "hdfs_host": hdfs_state.get("host"),
        "hdfs_path": hdfs_state.get("hdfs_path"),
        "signature": hdfs_state.get("signature"),
    }
    return {
        "dashboard_stats": stats or {},
        "evaluation_report": evaluation or {},
        "metadata": metadata or {},
        "data_source": data_source,
    }


@app.get("/api/v1/metadata")
async def metadata(request: Request) -> dict[str, Any]:
    return await request.app.state.store.document("metadata") or {}
