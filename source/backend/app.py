"""Async recommendation serving API backed by MongoDB and Redis.

Expected MongoDB documents:
  user_recommendations: {user_id, recommendations: [{rank, product_id, item_idx,
    brand, category_code, avg_price, als_score, purchase_prob}]}
  item_associations: {antecedent_idx, antecedent_product_id, consequents: [...]} 
  cluster_fallbacks: {cluster_id, cluster_avg_price, top_popular_items: [...]} 
  product_metadata: {product_id, item_idx, brand, category_code, avg_price,
    cluster_id}

Configure connection strings and collection names with environment variables.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field
from pymongo.errors import NetworkTimeout, PyMongoError, ServerSelectionTimeoutError
from redis.asyncio import Redis


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("recommendation_api")


MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
MONGODB_DATABASE = os.getenv("MONGODB_DATABASE", "recommendation_db")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", "3600"))
DB_TIMEOUT_SECONDS = float(os.getenv("DB_TIMEOUT_SECONDS", "3.0"))
DEFAULT_FALLBACK_CLUSTER_ID = int(os.getenv("DEFAULT_FALLBACK_CLUSTER_ID", "1"))

COLLECTION_USERS = os.getenv("MONGO_USERS_COLLECTION", "user_recommendations")
COLLECTION_ASSOCIATIONS = os.getenv("MONGO_ASSOCIATIONS_COLLECTION", "item_associations")
COLLECTION_CLUSTERS = os.getenv("MONGO_CLUSTERS_COLLECTION", "cluster_fallbacks")
COLLECTION_PRODUCTS = os.getenv("MONGO_PRODUCTS_COLLECTION", "product_metadata")


class RecommendationItem(BaseModel):
    rank: int
    product_id: str
    item_idx: int
    brand: Optional[str] = None
    category_code: Optional[str] = None
    avg_price: Optional[float] = None
    als_score: Optional[float] = None
    purchase_prob: Optional[float] = None


class UserRecommendationResponse(BaseModel):
    user_id: str
    strategy: str
    items: list[RecommendationItem] = Field(default_factory=list)


class CrossSellItem(BaseModel):
    product_id: str
    item_idx: int
    brand: Optional[str] = None
    category_code: Optional[str] = None
    avg_price: Optional[float] = None
    confidence: Optional[float] = None
    lift: Optional[float] = None


class CrossSellResponse(BaseModel):
    product_id: str
    recommendation_source: str
    items: list[CrossSellItem] = Field(default_factory=list)


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _recommendation_item(document: dict[str, Any], position: int) -> RecommendationItem:
    return RecommendationItem(
        rank=_as_int(document.get("rank"), position),
        product_id=str(document.get("product_id", "")),
        item_idx=_as_int(document.get("item_idx")),
        brand=document.get("brand"),
        category_code=document.get("category_code"),
        avg_price=document.get("avg_price"),
        als_score=document.get("als_score"),
        purchase_prob=document.get("purchase_prob"),
    )


def _cross_sell_item(document: dict[str, Any]) -> CrossSellItem:
    return CrossSellItem(
        product_id=str(document.get("consequent_product_id", document.get("product_id", ""))),
        item_idx=_as_int(document.get("consequent_idx", document.get("item_idx"))),
        brand=document.get("brand"),
        category_code=document.get("category_code"),
        avg_price=document.get("avg_price"),
        confidence=document.get("confidence"),
        lift=document.get("lift"),
    )


async def _cache_get(redis: Redis, key: str) -> Optional[dict[str, Any]]:
    try:
        payload = await redis.get(key)
        return json.loads(payload) if payload else None
    except Exception:
        # Cache outage should not prevent a MongoDB-backed response.
        logger.warning("Redis GET failed for key=%s; falling back to MongoDB", key, exc_info=True)
        return None


async def _cache_set(redis: Redis, key: str, value: dict[str, Any]) -> None:
    try:
        await redis.set(key, json.dumps(value, separators=(",", ":")), ex=CACHE_TTL_SECONDS)
    except Exception:
        logger.warning("Redis SET failed for key=%s", key, exc_info=True)


def _http_db_error(exc: Exception) -> HTTPException:
    if isinstance(
        exc,
        (asyncio.TimeoutError, TimeoutError, NetworkTimeout, ServerSelectionTimeoutError),
    ):
        return HTTPException(status_code=504, detail="Database request timed out")
    if isinstance(exc, PyMongoError):
        logger.exception("MongoDB request failed")
        return HTTPException(status_code=500, detail="MongoDB request failed")
    logger.exception("Database request failed", exc_info=exc)
    return HTTPException(status_code=500, detail="Database request failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    mongo_client = AsyncIOMotorClient(
        MONGODB_URI,
        serverSelectionTimeoutMS=int(DB_TIMEOUT_SECONDS * 1000),
        connectTimeoutMS=int(DB_TIMEOUT_SECONDS * 1000),
        socketTimeoutMS=int(DB_TIMEOUT_SECONDS * 1000),
        tz_aware=True,
    )
    redis_client = Redis.from_url(
        REDIS_URL,
        decode_responses=True,
        socket_connect_timeout=DB_TIMEOUT_SECONDS,
        socket_timeout=DB_TIMEOUT_SECONDS,
    )

    app.state.mongo_client = mongo_client
    app.state.db = mongo_client[MONGODB_DATABASE]
    app.state.redis = redis_client
    try:
        # Indexed equality lookups are required for predictable serving latency.
        await app.state.db[COLLECTION_USERS].create_index("user_id")
        await app.state.db[COLLECTION_ASSOCIATIONS].create_index("antecedent_idx")
        await app.state.db[COLLECTION_CLUSTERS].create_index("cluster_id")
        await app.state.db[COLLECTION_PRODUCTS].create_index("product_id")
        yield
    finally:
        mongo_client.close()
        await redis_client.aclose()


app = FastAPI(
    title="Multi-Stage Product Recommendation API",
    version="1.0.0",
    lifespan=lifespan,
)

WEB_DIR = Path(
    os.getenv("FRONTEND_DIR", str(Path(__file__).resolve().parent / "web"))
)
app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")


@app.get("/", include_in_schema=False)
async def storefront() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/health")
async def health(request: Request) -> dict[str, str]:
    """Basic liveness/readiness check for MongoDB and Redis."""
    try:
        await asyncio.wait_for(request.app.state.db.command("ping"), DB_TIMEOUT_SECONDS)
        await asyncio.wait_for(request.app.state.redis.ping(), DB_TIMEOUT_SECONDS)
    except Exception as exc:
        logger.exception("Health check failed")
        raise HTTPException(status_code=503, detail="A backing service is unavailable") from exc
    return {"status": "ok"}


@app.get(
    "/api/v1/recommendations/{user_id}",
    response_model=UserRecommendationResponse,
)
async def get_recommendations(
    user_id: str,
    request: Request,
    limit: int = Query(default=5, ge=1, le=30),
) -> UserRecommendationResponse:
    redis: Redis = request.app.state.redis
    cache_key = f"rec:user:{user_id}"

    cached = await _cache_get(redis, cache_key)
    if cached:
        response = UserRecommendationResponse(**cached)
        response.items = response.items[:limit]
        return response

    db = request.app.state.db
    try:
        document = await asyncio.wait_for(
            db[COLLECTION_USERS].find_one(
                {"user_id": user_id},
                {"_id": 0, "user_id": 1, "recommendations": 1},
            ),
            timeout=DB_TIMEOUT_SECONDS,
        )

        if document and document.get("recommendations"):
            stored = sorted(
                document["recommendations"],
                key=lambda item: (
                    -(item.get("purchase_prob") or 0.0),
                    item.get("rank", 10**9),
                ),
            )[:30]
            items = [_recommendation_item(row, i + 1) for i, row in enumerate(stored)]
            response = UserRecommendationResponse(
                user_id=user_id,
                strategy="personalized_reranked",
                items=items,
            )
        else:
            # Schema has cluster fallbacks but no global-popularity collection.
            # Use the configured default cluster (default ID 1); it can be changed
            # with DEFAULT_FALLBACK_CLUSTER_ID or replaced by a global-popular list.
            cluster_doc = await asyncio.wait_for(
                db[COLLECTION_CLUSTERS].find_one(
                    {"cluster_id": DEFAULT_FALLBACK_CLUSTER_ID},
                    {"_id": 0, "top_popular_items": 1},
                ),
                timeout=DB_TIMEOUT_SECONDS,
            )
            fallback_rows = (cluster_doc or {}).get("top_popular_items", [])[:10]
            items = []
            for i, row in enumerate(fallback_rows[:30]):
                item = dict(row)
                item.setdefault("rank", i + 1)
                items.append(_recommendation_item(item, i + 1))
            response = UserRecommendationResponse(
                user_id=user_id,
                strategy="cold_start_fallback",
                items=items,
            )

        await _cache_set(redis, cache_key, response.dict())
        response.items = response.items[:limit]
        return response
    except HTTPException:
        raise
    except Exception as exc:
        raise _http_db_error(exc) from exc


@app.get("/api/v1/cross-sell/{product_id}", response_model=CrossSellResponse)
async def get_cross_sell(
    product_id: str,
    request: Request,
    limit: int = Query(default=3, ge=1, le=10),
) -> CrossSellResponse:
    redis: Redis = request.app.state.redis
    cache_key = f"cross_sell:{product_id}"

    cached = await _cache_get(redis, cache_key)
    if cached:
        response = CrossSellResponse(**cached)
        response.items = response.items[:limit]
        return response

    db = request.app.state.db
    try:
        product = await asyncio.wait_for(
            db[COLLECTION_PRODUCTS].find_one(
                {"product_id": product_id},
                {"_id": 0, "product_id": 1, "item_idx": 1, "cluster_id": 1},
            ),
            timeout=DB_TIMEOUT_SECONDS,
        )
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")

        item_idx = _as_int(product.get("item_idx"), -1)
        association = None
        if item_idx >= 0:
            association = await asyncio.wait_for(
                db[COLLECTION_ASSOCIATIONS].find_one(
                    {"antecedent_idx": item_idx},
                    {"_id": 0, "consequents": 1},
                ),
                timeout=DB_TIMEOUT_SECONDS,
            )

        consequents = (association or {}).get("consequents", [])
        if consequents:
            consequents = sorted(
                consequents,
                key=lambda row: (
                    -(row.get("lift") or 0.0),
                    -(row.get("confidence") or 0.0),
                ),
            )[:10]
            response = CrossSellResponse(
                product_id=product_id,
                recommendation_source="FP-Growth",
                items=[_cross_sell_item(row) for row in consequents],
            )
        else:
            cluster_id = product.get("cluster_id")
            if cluster_id is None:
                raise HTTPException(
                    status_code=404,
                    detail="No association rule or cluster fallback for product",
                )
            cluster_doc = await asyncio.wait_for(
                db[COLLECTION_CLUSTERS].find_one(
                    {"cluster_id": _as_int(cluster_id)},
                    {"_id": 0, "top_popular_items": 1},
                ),
                timeout=DB_TIMEOUT_SECONDS,
            )
            fallback_rows = (cluster_doc or {}).get("top_popular_items", [])
            fallback_rows = [
                row for row in fallback_rows
                if _as_int(row.get("item_idx"), -2) != item_idx
            ][:10]
            response = CrossSellResponse(
                product_id=product_id,
                recommendation_source="K-Means fallback",
                items=[_cross_sell_item(row) for row in fallback_rows],
            )

        await _cache_set(redis, cache_key, response.dict())
        response.items = response.items[:limit]
        return response
    except HTTPException:
        raise
    except Exception as exc:
        raise _http_db_error(exc) from exc

