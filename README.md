# Cosmetics Multi-Stage Recommendation App

Full-stack cosmetics recommendation application. The static storefront deploys
to Vercel; FastAPI deploys to Render; MongoDB Atlas stores Spark batch exports;
and Render Key Value provides Redis caching.

## Repository deliverables

- `source/backend/`: clean FastAPI backend source for submission.
- `source/frontend/`: clean HTML/CSS/JavaScript frontend source for submission.
- `Dockerfile` and `render.yaml`: Render API and Redis deployment setup.
- `source/frontend/vercel.json`: Vercel static frontend build setup.
- `scripts/`: import Spark JSON exports into MongoDB.
- `locustfile.py`: optional HTTP load generator.

The Spark model is not run inside HTTP requests. Export batch recommendations
from Kaggle, seed MongoDB, then the API serves them with low-latency lookups.

## Online deployment: Vercel + Render + Atlas

The repository contains deployment configuration, but the online services and
dataset are not provisioned or populated by a GitHub push. Create the accounts
and secrets in each provider dashboard; never paste database credentials into
GitHub or chat.

1. **MongoDB Atlas:** Create a free cluster and database user. Configure Network
   Access so Render can reach it (for a student demo, Atlas may require allowing
   `0.0.0.0/0`; use a strong database password and restrict access to this
   database user). Copy the Atlas connection URI.
2. **Render API + Redis:** In Render, create a Blueprint from this repository
   and apply `render.yaml`. Set `MONGODB_URI` in the API service's secret
   environment variable, then deploy. The Blueprint provisions a FastAPI web
   service and a Redis Key Value service. Check
   `https://<render-service>.onrender.com/health` after Atlas is reachable.
3. **Vercel frontend:** Import the same GitHub repository in Vercel and set
   **Root Directory** to `source/frontend`. Keep the detected build settings
   from `vercel.json` (`npm run build`, output `dist`). Add the environment
   variable `RECSYS_API_BASE_URL=https://<render-service>.onrender.com` and
   redeploy. `render.yaml` currently allows cross-origin requests so the first
   deployment works; after Vercel provides its domain, set Render's
   `CORS_ORIGINS` to that exact `https://...vercel.app` origin (and any custom
   domain), then redeploy the API.
4. **Populate Atlas:** Spark results are not in the online database yet. Run
   `scripts/export_kaggle_spark.py` from the Kaggle notebook after the models and
   DataFrames exist, download the generated `mongo_exports` output, and import
   it from a trusted machine with `scripts/import_mongo.py` and the Atlas URI.
   Instructions and the expected input variables are below. The frontend can
   deploy before this step, but personalized recommendations and cross-sell
   need the imported records.
5. Visit the Vercel URL. Render continues to provide `/docs` and `/health`.

Account credentials are not stored in this repository. Free hosting tiers can
sleep or have storage/availability limits, which may affect demo latency.

### Export Spark results from Kaggle

Copy `scripts/export_kaggle_spark.py` into the Kaggle notebook (or clone this
repository there), then run after all training variables exist:

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

The `.env` file must contain valid MongoDB and Redis connection strings. The
FastAPI process serves the storefront locally at `http://localhost:8000/`.

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
