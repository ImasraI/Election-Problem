import os

import redis
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

TOKEN = os.environ.get("REST_TOKEN", "")
client = redis.Redis.from_url(
    os.environ.get("REDIS_URL", "redis://redis:6379"), decode_responses=True
)
app = FastAPI()


@app.get("/health")
def health():
    try:
        client.ping()
        return {"ok": True}
    except redis.RedisError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=503)


@app.post("/")
async def command(request: Request):
    if TOKEN and request.headers.get("authorization") != f"Bearer {TOKEN}":
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    try:
        cmd = await request.json()
    except Exception:
        return JSONResponse({"error": "body must be a JSON array"}, status_code=400)
    if not isinstance(cmd, list) or not cmd:
        return JSONResponse({"error": "body must be a non-empty JSON array"}, status_code=400)
    try:
        result = await run_in_threadpool(client.execute_command, *[str(part) for part in cmd])
    except redis.RedisError as exc:
        return JSONResponse({"error": str(exc)})
    if isinstance(result, bytes):
        result = result.decode()
    elif result is True:
        result = "OK"
    return {"result": result}
