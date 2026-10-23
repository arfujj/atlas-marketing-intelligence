# Deploying ATLAS

The API ships with its data baked in (the serving DuckDB is built inside the image from the
seeded simulator and the committed GA4 extracts), so neither service needs credentials,
secrets or a database.

## Option A: everything on Render (one blueprint)

1. Push the repository to GitHub.
2. In Render: **New → Blueprint**, select the repository. It reads `render.yaml` and creates
   `atlas-api` and `atlas-web` (both free plan, built from the Dockerfiles).
3. When asked for `ATLAS_API_URL`, enter the API's URL (shown on the `atlas-api` service page,
   e.g. `https://atlas-api-xxxx.onrender.com`). If the API URL is not known yet, deploy, copy it,
   then set it under `atlas-web → Environment` and redeploy the web service.
4. Check `https://<api>/health` returns `{"status":"ok","db":true,...}`, then open the web URL.

Free instances sleep after ~15 minutes idle; the first visit afterwards takes about a minute.

## Option B: web on Vercel, API on Render

1. Deploy only `atlas-api` on Render (as above, or **New → Web Service → Docker**, health
   check `/health`).
2. Web on Vercel:
   ```bash
   cd web
   vercel login                       # once, in your browser
   vercel link                        # create/link the project (root directory: web)
   vercel env add ATLAS_API_URL production   # paste the API URL
   vercel --prod
   ```

## Check a deployment

```bash
cd web && WEB_URL=https://<your-web-url> npm run e2e
```
runs the same Playwright suite CI runs locally (every page, desktop and phone, the optimizer).
