# ATLAS web

Next.js (App Router, Next 16 with Cache Components) front end for the ATLAS API. Every page is a
static shell; data streams in from the API inside `<Suspense>`.

```bash
make api            # from the repo root: FastAPI on :8000
npm run dev -- -p 3210
npm test            # Vitest: formatting rules
npm run e2e         # Playwright: every page at desktop and phone width, the optimizer, truth toggle
npm run gen:api     # regenerate request types from openapi.json
```

`ATLAS_API_URL` points the server components at the API (default `http://127.0.0.1:8000`).
