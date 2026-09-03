import os
from functools import partial
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

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
CATCH = (ValueError, PermissionError, RuntimeError)


def fail(exc, code=400):
    if isinstance(exc, PermissionError):
        status = 403
    elif isinstance(exc, RuntimeError):
        status = 503
    else:
        status = code
    return JSONResponse({"error": str(exc)}, status_code=status)


def require_user(request: Request):
    token = workshop.token_from_headers(request.headers)
    user = workshop.user_from_token(token)
    if not user:
        return None, JSONResponse({"error": "وارد شوید."}, status_code=401)
    return user, None


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "model": MODEL_NAME,
        "store": workshop.store_kind(),
        "live": workshop.live_classroom_ok(),
    }


@app.post("/api/auth/login")
async def auth_login(request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Body must be JSON."}, status_code=400)
    try:
        return workshop.login(
            body.get("username") or "",
            body.get("password") or "",
            body.get("name") or "",
            body.get("team") or "",
        )
    except ValueError as exc:
        return fail(exc, 401)
    except RuntimeError as exc:
        return fail(exc)


@app.post("/api/auth/logout")
async def auth_logout(request: Request):
    workshop.logout(workshop.token_from_headers(request.headers))
    return {"ok": True}


@app.get("/api/auth/me")
def auth_me(request: Request):
    user, err = require_user(request)
    if err:
        return err
    try:
        return {"user": workshop.snapshot(user)["me"]}
    except RuntimeError as exc:
        return fail(exc)


@app.get("/api/sync")
def sync(request: Request):
    user, err = require_user(request)
    if err:
        return err
    try:
        return workshop.snapshot(user)
    except RuntimeError as exc:
        return fail(exc)


@app.post("/api/unlock")
async def unlock(request: Request):
    user, err = require_user(request)
    if err:
        return err
    try:
        body = await request.json()
        unlocked = workshop.unlock_panel(user, body.get("id") or "")
        return {"unlocked": unlocked}
    except CATCH as exc:
        return fail(exc)


@app.post("/api/hide")
async def hide(request: Request):
    user, err = require_user(request)
    if err:
        return err
    try:
        body = await request.json()
        unlocked = workshop.hide_panel(user, body.get("id") or "")
        return {"unlocked": unlocked}
    except CATCH as exc:
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
    except CATCH as exc:
        return fail(exc)


@app.get("/api/admin/users")
def admin_list_users(request: Request):
    user, err = require_user(request)
    if err:
        return err
    try:
        return {"users": workshop.list_users(user)}
    except CATCH as exc:
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
    except CATCH as exc:
        return fail(exc)


@app.post("/api/admin/admins")
async def admin_create_admin(request: Request):
    user, err = require_user(request)
    if err:
        return err
    try:
        body = await request.json()
        created = workshop.create_admin(user, body.get("username") or "", body.get("password") or "")
        return {"user": created}
    except CATCH as exc:
        return fail(exc)


@app.post("/api/state1")
async def state1_idea(request: Request):
    user, err = require_user(request)
    if err:
        return err
    try:
        body = await request.json()
        idea = workshop.set_state1_idea(user, body.get("text") or "")
        return {"idea": idea}
    except CATCH as exc:
        return fail(exc)


@app.post("/api/state1/evaluate")
async def state1_evaluate(request: Request):
    user, err = require_user(request)
    if err:
        return err
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Body must be JSON."}, status_code=400)
    try:
        idea = await run_in_threadpool(workshop.process_state1_idea, user, body.get("id") or "")
        return {"criteria": idea["criteria"], "prompt": idea["text"], "idea": idea}
    except CATCH as exc:
        return fail(exc)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=502)


@app.post("/api/ideas/delete")
async def ideas_delete(request: Request):
    user, err = require_user(request)
    if err:
        return err
    try:
        body = await request.json()
        return workshop.delete_idea(user, body.get("id") or "", body.get("source") or "")
    except CATCH as exc:
        return fail(exc)


@app.post("/api/admin/reset")
def admin_reset(request: Request):
    user, err = require_user(request)
    if err:
        return err
    try:
        workshop.reset_workshop(user)
        return {"ok": True}
    except CATCH as exc:
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
    except CATCH as exc:
        return fail(exc)


@app.post("/api/vote/present")
def vote_present(request: Request):
    user, err = require_user(request)
    if err:
        return err
    try:
        return workshop.present_votes(user)
    except CATCH as exc:
        return fail(exc)


@app.post("/api/vote/reset")
def vote_reset(request: Request):
    user, err = require_user(request)
    if err:
        return err
    try:
        return workshop.reset_voting(user)
    except CATCH as exc:
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
    except CATCH as exc:
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
        idea = await run_in_threadpool(workshop.submit_idea, user, body.get("prompt") or "")
        return {"criteria": idea["criteria"], "prompt": idea["text"], "idea": idea}
    except CATCH as exc:
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
        idea = await run_in_threadpool(
            partial(
                workshop.add_examples,
                user,
                idea_id=body.get("id") or "",
                prompt=body.get("prompt") or "",
                criteria=body.get("criteria"),
            )
        )
        return {"examples": idea.get("examples") or [], "idea": idea}
    except CATCH as exc:
        return fail(exc)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=502)


if not os.environ.get("VERCEL"):
    app.mount("/", StaticFiles(directory=str(STATIC), html=True), name="public")
