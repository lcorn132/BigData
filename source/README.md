# Source package for thesis submission

This directory contains the application source separated into frontend and
backend. Deployment manifests and container build files live at repository root.

## Layout

- `backend/app.py`: FastAPI application, async MongoDB/Redis access, cache,
  recommendation endpoints, fallback routing and health check.
- `frontend/index.html`: storefront structure.
- `frontend/static/styles.css`: responsive presentation.
- `frontend/static/app.js`: user interaction and API client.

Run instructions and deployment configuration are in the repository-root
`README.md`. The backend serves this frontend when `FRONTEND_DIR` points at the
`source/frontend` directory.
