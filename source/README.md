# Source package for thesis submission

This directory contains the application source separated into frontend and
backend. Deploy the frontend on Vercel with `frontend` as its Root Directory;
deploy the backend on Render using the repository-root `render.yaml` Blueprint.

## Layout

- `backend/app.py`: FastAPI application, async MongoDB/Redis access, cache,
  recommendation endpoints, fallback routing and health check.
- `frontend/index.html`: storefront structure.
- `frontend/static/styles.css`: responsive presentation.
- `frontend/static/app.js`: user interaction and API client.
- `frontend/build.mjs` and `frontend/vercel.json`: Vercel static build. Set
  `RECSYS_API_BASE_URL` in Vercel to the Render service URL.

## Run

From the repository root:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r source/requirements.txt
cp source/.env.example .env
# Set MONGODB_URI and REDIS_URL in .env, then:
set -a && . ./.env && set +a
uvicorn source.backend.app:app --host 127.0.0.1 --port 8000
```

The app serves the frontend at `/`, its API at `/api/v1/...`, and OpenAPI docs
at `/docs`. Keep real credentials in environment variables, not in this source
package. For MongoDB collection schema and data import, see repository-root
`README.md`.

The online database is initially empty. Export the trained Spark outputs from
Kaggle and import the generated JSON into MongoDB Atlas before expecting
recommendation results. Vercel hosts only the static frontend; it does not host
FastAPI, MongoDB, or Redis.
