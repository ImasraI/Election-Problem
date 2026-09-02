import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from llm_core import MODEL_NAME
import workshop

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC = Path(__file__).resolve().parent / "public"


def fail(exc, code=400):
    status = 403 if isinstance(exc, PermissionError) else code
    return JSONResponse({"error": str(exc)}, status_code=status)


def require_user(request: Request):
    token = workshop.token_from_headers(request.headers)
    user = workshop.user_from_token(token)
    if not user:
        return None, JSONResponse({"error": "وارد شوید."}, status_code=401)
    return user, None


@app.get("/api/health")
def health():
    return {"ok": True, "model": MODEL_NAME}


@app.post("/api/auth/login")
async def auth_login(request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Body must be JSON."}, status_code=400)
    try:
        result = workshop.login(
            body.get("username") or "",
            body.get("password") or "",
            body.get("name") or "",
            body.get("team") or "",
        )
        return result
    except ValueError as exc:
        return fail(exc, 401)


@app.post("/api/auth/logout")
async def auth_logout(request: Request):
    workshop.logout(workshop.token_from_headers(request.headers))
    return {"ok": True}


@app.get("/api/auth/me")
def auth_me(request: Request):
    user, err = require_user(request)
    if err:
        return err
    return {"user": workshop.snapshot(user)["me"]}


@app.get("/api/sync")
def sync(request: Request):
    user, err = require_user(request)
    if err:
        return err
    return workshop.snapshot(user)


@app.post("/api/unlock")
async def unlock(request: Request):
    user, err = require_user(request)
    if err:
        return err
    try:
        body = await request.json()
        unlocked = workshop.unlock_panel(user, body.get("id") or "")
        return {"unlocked": unlocked}
    except (ValueError, PermissionError) as exc:
        return fail(exc)


@app.post("/api/admin/users")
async def admin_create_user(request: Request):
    user, err = require_user(request)
    if err:
        return err
    try:
        body = await request.json()
        created = workshop.create_student(user, body.get("username") or "", body.get("password") or "")
        return {"user": created}
    except (ValueError, PermissionError) as exc:
        return fail(exc)


@app.get("/api/admin/users")
def admin_list_users(request: Request):
    user, err = require_user(request)
    if err:
        return err
    try:
        return {"users": workshop.list_users(user)}
    except PermissionError as exc:
        return fail(exc)


@app.post("/api/admin/users/delete")
async def admin_delete_user(request: Request):
    user, err = require_user(request)
    if err:
        return err
    try:
        body = await request.json()
        workshop.delete_student(user, body.get("username") or "")
        return {"ok": True}
    except (ValueError, PermissionError) as exc:
        return fail(exc)


@app.post("/api/admin/reset")
def admin_reset(request: Request):
    user, err = require_user(request)
    if err:
        return err
    try:
        workshop.reset_workshop(user)
        return {"ok": True}
    except PermissionError as exc:
        return fail(exc)


@app.post("/api/vote")
async def vote_cast(request: Request):
    user, err = require_user(request)
    if err:
        return err
    try:
        body = await request.json()
        ballot = workshop.set_vote(user, body.get("rank") or "")
        return {"vote": ballot}
    except (ValueError, PermissionError) as exc:
        return fail(exc)


@app.post("/api/vote/present")
def vote_present(request: Request):
    user, err = require_user(request)
    if err:
        return err
    try:
        return workshop.present_votes(user)
    except PermissionError as exc:
        return fail(exc)


@app.post("/api/arrows")
async def arrows_set(request: Request):
    user, err = require_user(request)
    if err:
        return err
    try:
        body = await request.json()
        profiles = workshop.set_arrows(user, body.get("profiles"))
        return {"arrows": profiles}
    except (ValueError, PermissionError) as exc:
        return fail(exc)


@app.post("/api/evaluate")
async def evaluate(request: Request):
    user, err = require_user(request)
    if err:
        return err
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Body must be JSON."}, status_code=400)
    try:
        idea = workshop.submit_idea(user, body.get("prompt") or "")
        return {"criteria": idea["criteria"], "prompt": idea["text"], "idea": idea}
    except ValueError as exc:
        return fail(exc)
    except PermissionError as exc:
        return fail(exc)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=502)


@app.post("/api/examples")
async def examples(request: Request):
    user, err = require_user(request)
    if err:
        return err
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Body must be JSON."}, status_code=400)
    try:
        idea = workshop.add_examples(
            user,
            idea_id=body.get("id") or "",
            prompt=body.get("prompt") or "",
            criteria=body.get("criteria"),
        )
        return {"examples": idea.get("examples") or [], "idea": idea}
    except (ValueError, PermissionError) as exc:
        return fail(exc)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=502)


if not os.environ.get("VERCEL"):
    app.mount("/", StaticFiles(directory=str(STATIC), html=True), name="public")
