# Cosmetics Multi-Stage Recommendation App

Full-stack FastAPI + static frontend application for the Spark cosmetics
recommendation pipeline. The web interface calls the same-origin FastAPI
endpoints; MongoDB stores batch-exported recommendations and metadata, and
Redis caches API responses.

## Repository deliverables

- `source/backend/`: clean FastAPI backend source for submission.
- `source/frontend/`: clean HTML/CSS/JavaScript frontend source for submission.
- `Dockerfile` and `render.yaml`: GitHub-connected Render deployment setup.
- `scripts/`: import Spark JSON exports into MongoDB.
- `locustfile.py`: optional HTTP load generator.

The Spark model is not run inside HTTP requests. Export batch recommendations
from Kaggle, seed MongoDB, then the API serves them with low-latency lookups.

## Online deployment

1. Create a MongoDB Atlas cluster and database user. Add the Render service's
   outbound network to the Atlas IP access list. Put the Atlas URI in Render's
   `MONGODB_URI` secret field; do not commit it.
2. In Render, create a Blueprint from this GitHub repository and apply
   `render.yaml`. It provisions the web API and a Redis Key Value service.
3. Set `MONGODB_URI` in the Render service environment. Wait for `/health` to
   report `{"status":"ok"}`.
4. Import Spark exports using `scripts/import_mongo.py` with the Atlas URI.
5. Open the Render service URL. The storefront is `/`; API docs are `/docs`.

MongoDB/Render account credentials are not stored in this repository. Render's
free web plan may sleep when idle; choose an always-on plan for a persistent
demonstration. A Render Key Value plan may also have storage/availability limits.

### Export Spark results from Kaggle

Clone this repository in Kaggle (or copy `scripts/export_kaggle_spark.py` into
the notebook), then run after all training variables exist:

```python
from scripts.export_kaggle_spark import export_kaggle_results

export_kaggle_results(
    output_dir="/kaggle/working/mongo_exports",
    als_model=als_model,
    reranker_model=reranker_model,
    assembler=assembler,
    user_features=user_features,
    user_mapping=user_mapping,
    product_mapping=product_mapping,
    product_metadata=product_metadata,
    association_rules=association_rules,
    item_clusters=item_clusters,
    train=train,
)
```

Spark writes partitioned JSON directories for all users' top 30 re-ranked items,
singleton FP-Growth rules, product metadata with cluster IDs, and top 100 popular
items per cluster. Download `mongo_exports` from Kaggle Output, place it on a
trusted machine, then run the importer there with `MONGODB_URI` configured in
the shell environment. Do not commit the URI or include it in command history.

The exporter computes up to 50 ALS candidates for each mapped user; exporting
273k users may take several minutes and produces a large output. Keep the export
in Kaggle output/storage rather than GitHub. The web API only needs the imported
MongoDB records at serving time.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
set -a && . ./.env && set +a
FRONTEND_DIR="$PWD/source/frontend" \
  uvicorn source.backend.app:app --reload --port 8000
```

The `.env` file must contain valid local/online MongoDB and Redis connection
strings. Frontend is served at `http://localhost:8000/`.

## API

- `GET /api/v1/recommendations/{user_id}?limit=5`
- `GET /api/v1/cross-sell/{product_id}?limit=3`
- `GET /health`
- `GET /docs`

## Load test

Use valid IDs from the database:

```bash
LOCUST_USER_IDS="557956487" LOCUST_PRODUCT_IDS="5826000" \
  locust -f locustfile.py --host https://YOUR-RENDER-SERVICE.onrender.com \
  -u 100 -r 20 -t 3m --headless --csv=results/run --html=results/report.html
```

Increase `-u` to 500 for the higher-concurrency run. Locust reports P95/P99,
request rate, and failures in its terminal summary and output files.
