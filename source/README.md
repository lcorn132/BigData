# Source package for thesis submission

This directory contains the application source separated into frontend and
backend. Deployment manifests and container build files live at repository root.

## Layout

- `backend/app.py`: FastAPI application, async MongoDB/Redis access, cache,
  recommendation endpoints, fallback routing and health check.
- `frontend/index.html`: storefront structure.
- `frontend/static/styles.css`: responsive presentation.
- `frontend/static/app.js`: user interaction and API client.

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
