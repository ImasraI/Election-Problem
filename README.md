# Election-Problem (Vercel)

Vercel clone of the social-choice workshop. Classroom state lives in **Upstash Redis** (same REST API the original Vercel deploy used). This copy has no Docker / self-host files.

## Deploy on Vercel

1. Import this folder as a Vercel project (GitHub import, or `npx vercel` from this directory).
2. Framework should detect **FastAPI** from `pyproject.toml` (`entrypoint = "app:app"`).
3. Open the project → **Settings → Environment Variables** and set:
   - `ORCAROUTER_API_KEY` — LLM key
   - `ADMIN_PASSWORD` — password for the `admin` account
4. For a live classroom (many voters at once), add Redis:
   - **Storage → Create Database → Redis (Upstash)**
   - Connect it to this project so Vercel injects:
     - `UPSTASH_REDIS_REST_URL`
     - `UPSTASH_REDIS_REST_TOKEN`
5. Redeploy.

Without Upstash, Vercel can still run, but each serverless instance has its own `/tmp` file store — votes, lobby, and sessions will **not** stay in sync. The login page warns when `/api/health` returns `"live": false`.

## How storage works

`workshop.py` already talks to Upstash over HTTPS:

- `UPSTASH_REDIS_REST_URL` + `UPSTASH_REDIS_REST_TOKEN` → Redis (`store: "redis"`, `live: true`)
- otherwise on Vercel → `/tmp/kargah-data/workshop.json` (not shared)
- locally without Redis → `data/workshop.json`

## Local run

```bat
start.bat
```

or:

```
pip install -r requirements.txt
copy .env.example .env
# put ORCAROUTER_API_KEY in .env
python llm.py
```

Open http://127.0.0.1:8765/ — the lobby is the home page. Mentors use `login.html` (`admin` / `ADMIN_PASSWORD`, default `admin`).
