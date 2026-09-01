from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from llm_core import (
    MODEL_NAME,
    evaluate_criteria,
    generate_examples,
    normalize_criteria,
)

app = FastAPI()


@app.get("/api/health")
def health():
    return {"ok": True, "model": MODEL_NAME}


@app.post("/api/evaluate")
async def evaluate(request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Body must be JSON."}, status_code=400)
    prompt = str((body or {}).get("prompt") or "").strip()
    if not prompt:
        return JSONResponse({"error": "prompt is required."}, status_code=400)
    try:
        criteria = evaluate_criteria(prompt)
        return {"criteria": criteria, "prompt": prompt}
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=502)


@app.post("/api/examples")
async def examples(request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Body must be JSON."}, status_code=400)
    prompt = str((body or {}).get("prompt") or "").strip()
    if not prompt:
        return JSONResponse({"error": "prompt is required."}, status_code=400)
    try:
        criteria = normalize_criteria(body.get("criteria"))
        result = generate_examples(prompt, criteria)
        return {"examples": result, "prompt": prompt}
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=502)
