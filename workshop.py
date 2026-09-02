import hashlib
import hmac
import json
import os
import random
import re
import secrets
import threading
import time
from copy import deepcopy
from pathlib import Path

import requests

from llm_core import evaluate_criteria, generate_examples, normalize_criteria

ROOT = Path(__file__).resolve().parent


def _load_dotenv() -> None:
    path = ROOT / ".env"
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        name = name.strip()
        value = value.strip().strip("\"'")
        if name and name not in os.environ:
            os.environ[name] = value


_load_dotenv()
if os.environ.get("VERCEL"):
    DATA_DIR = Path("/tmp/kargah-data")
else:
    DATA_DIR = ROOT / "data"
DATA_PATH = DATA_DIR / "workshop.json"
STORE_KEY = "kargah:workshop"
LOCK_KEY = "kargah:workshop:lock"

MAX_STUDENTS = 120
MAX_ADMINS = 20
STUDENTS_PER_ADMIN = 6
SESSION_TTL = 60 * 60 * 16
PBKDF2_ROUNDS = 120_000
CRITERIA_KEYS = ["AAW", "CWC", "UNAN", "MONO", "IIA"]
POINTS_PER_CRITERION = 10
USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{2,32}$")

_thread_lock = threading.Lock()


def _redis_creds():
    url = (
        os.environ.get("UPSTASH_REDIS_REST_URL")
        or os.environ.get("KV_REST_API_URL")
        or os.environ.get("REDIS_REST_URL")
        or ""
    ).rstrip("/")
    token = (
        os.environ.get("UPSTASH_REDIS_REST_TOKEN")
        or os.environ.get("KV_REST_API_TOKEN")
        or os.environ.get("REDIS_REST_TOKEN")
        or ""
    )
    if url and token:
        return url, token
    return "", ""


def uses_redis() -> bool:
    url, token = _redis_creds()
    return bool(url and token)


def store_kind() -> str:
    return "redis" if uses_redis() else "file"


def live_classroom_ok() -> bool:
    return uses_redis() or not os.environ.get("VERCEL")


def _redis_call(*cmd):
    url, token = _redis_creds()
    response = requests.post(
        url,
        headers={"Authorization": f"Bearer {token}"},
        json=list(cmd),
        timeout=10,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("error"):
        raise RuntimeError(payload["error"])
    return payload.get("result")


class _StoreLock:
    def __enter__(self):
        _thread_lock.acquire()
        self._redis = uses_redis()
        self._token = ""
        if self._redis:
            self._token = secrets.token_hex(8)
            for _ in range(40):
                ok = _redis_call("SET", LOCK_KEY, self._token, "NX", "EX", 8)
                if ok:
                    break
                time.sleep(0.05)
            else:
                _thread_lock.release()
                raise RuntimeError("Classroom store is busy. Retry.")
        return self

    def __exit__(self, *args):
        try:
            if self._redis and self._token:
                current = _redis_call("GET", LOCK_KEY)
                if current == self._token:
                    _redis_call("DEL", LOCK_KEY)
        finally:
            _thread_lock.release()


_lock = _StoreLock()

ARROWS_ORDERS = {
    0: ["BAC", "BAC", "BCA", "BAC", "CAB", "ACB", "ACB", "CAB", "ACB"],
    1: ["BAC", "BAC", "BCA", "BAC", "BCA", "ACB", "ACB", "CAB", "ACB"],
    2: ["BAC", "BAC", "BCA", "BAC", "BCA", "ACB", "ACB", "CAB", "ACB"],
}


def default_arrows():
    return [
        [{"id": i + 1, "rank": list(s)} for i, s in enumerate(ARROWS_ORDERS[pi])]
        for pi in range(3)
    ]


def _hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), PBKDF2_ROUNDS)
    return f"{salt}${dk.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        salt, dk = stored.split("$", 1)
    except ValueError:
        return False
    test = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), PBKDF2_ROUNDS).hex()
    return hmac.compare_digest(test, dk)


PANEL_IDS = [
    "vote", "s1", "s2", "s3",
    "s4", "s4-1", "s4-2", "s4-3", "s4-4", "s4-5",
    "s5",
    "s6", "s6-1", "s6-2", "s6-3", "s6-4", "s6-5", "s6-6",
    "s8", "s7",
]


def is_owner(user) -> bool:
    return (user or {}).get("role") == "owner"


def is_admin(user) -> bool:
    return (user or {}).get("role") == "admin"


def is_staff(user) -> bool:
    return is_owner(user) or is_admin(user)


def _admin_password_env() -> str:
    return (os.environ.get("ADMIN_PASSWORD") or "").strip()


def _admin_password_fp(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def _apply_admin_password(data: dict) -> bool:
    password = _admin_password_env()
    if not password:
        return False
    fp = _admin_password_fp(password)
    if data.get("_admin_pw_fp") == fp:
        return False
    admin = data.setdefault("users", {}).get("admin")
    if not admin:
        return False
    admin["password"] = _hash_password(password)
    data["_admin_pw_fp"] = fp
    return True


def _blank() -> dict:
    admin_password = _admin_password_env() or "admin"
    return {
        "version": 1,
        "unlocked": ["vote"],
        "vote_revealed": False,
        "vote_display": [],
        "votes": {},
        "state1_ideas": [],
        "arrows": default_arrows(),
        "users": {
            "admin": {
                "username": "admin",
                "password": _hash_password(admin_password),
                "role": "owner",
                "name": "Admin",
                "team": "",
                "points": 0,
                "used_state5": False,
                "used_state1": False,
                "sponsor": "",
                "unlocked": ["vote"],
            }
        },
        "sessions": {},
        "_admin_pw_fp": _admin_password_fp(admin_password),
    }


def _normalize(data: dict) -> dict:
    data.setdefault("version", 1)
    data.setdefault("unlocked", ["vote"])
    data.setdefault("vote_revealed", False)
    data.setdefault("vote_display", [])
    data.setdefault("votes", {})
    data.setdefault("ideas", [])
    data.setdefault("state1_ideas", [])
    data.setdefault("arrows", default_arrows())
    data.setdefault("users", {})
    data.setdefault("sessions", {})
    admin = data["users"].get("admin")
    if admin and admin.get("role") == "admin" and not admin.get("sponsor"):
        admin["role"] = "owner"
        admin.setdefault("name", "Admin")
    if "admin" not in data["users"]:
        data["users"]["admin"] = _blank()["users"]["admin"]
    for user in data["users"].values():
        user.setdefault("sponsor", "")
        user.setdefault("unlocked", ["vote"] if user.get("role") == "student" else list(PANEL_IDS))
        user.setdefault("hidden", [])
        if user.get("role") in ("owner", "admin"):
            have = set(user.get("unlocked") or [])
            prev = set(PANEL_IDS) - {"s6-6"}
            if prev <= have and "s6-6" not in have:
                user["unlocked"] = list(user["unlocked"]) + ["s6-6"]
        if user.get("role") == "admin" and user.get("username") == "admin":
            user["role"] = "owner"
        if user.get("role") == "owner" and user.get("name") == "مالک":
            user["name"] = "Admin"
    if _apply_admin_password(data):
        data["_persist_admin_pw"] = True
    shown = set(data.get("unlocked") or [])
    if "s6-6" not in shown and {"s6-1", "s6-2", "s6-3", "s6-4", "s6-5"} <= shown:
        data["unlocked"] = list(data["unlocked"]) + ["s6-6"]
    if "vote" not in data["unlocked"]:
        data["unlocked"] = ["vote"] + list(data["unlocked"])
    return data


def _load() -> dict:
    if uses_redis():
        raw = _redis_call("GET", STORE_KEY)
        if not raw:
            data = _blank()
            _dump(data)
            return data
        try:
            data = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            data = _blank()
            _dump(data)
            return data
        data = _normalize(data)
        if data.pop("_persist_admin_pw", False):
            _dump(data)
        return data
    if not DATA_PATH.is_file():
        data = _blank()
        _dump(data)
        return data
    try:
        data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        data = _blank()
        _dump(data)
        return data
    data = _normalize(data)
    if data.pop("_persist_admin_pw", False):
        _dump(data)
    return data


def _dump(data: dict) -> None:
    payload = json.dumps(data, ensure_ascii=False)
    if uses_redis():
        _redis_call("SET", STORE_KEY, payload)
        return
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = DATA_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(DATA_PATH)


def _bump(data: dict) -> None:
    data["version"] = int(data.get("version") or 0) + 1


def _class_key(user: dict) -> str:
    if not user:
        return ""
    if user.get("role") == "student":
        return (user.get("sponsor") or "").strip()
    return (user.get("username") or "").strip()


def _idea_class(data: dict, idea: dict) -> str:
    if idea.get("class_id"):
        return idea["class_id"]
    author = (data.get("users") or {}).get(idea.get("username") or "")
    return _class_key(author) if author else ""


def _class_ideas(data: dict, actor: dict, ideas) -> list:
    key = _class_key(actor)
    return [deepcopy(item) for item in (ideas or []) if _idea_class(data, item) == key]


def _random_rank() -> str:
    order = ["A", "B", "C"]
    random.shuffle(order)
    return ">".join(order)


def _fake_display_votes(real_votes: dict) -> list:
    people = list((real_votes or {}).values())
    if not people:
        n = random.randint(9, 14)
        people = [{"name": f"Voter {i}", "team": ""} for i in range(1, n + 1)]
    fake = []
    for person in people:
        fake.append({
            "rank": _random_rank(),
            "name": person.get("name") or "Voter",
            "team": person.get("team") or "",
        })
    return fake


def _public_user(user: dict) -> dict:
    return {
        "username": user["username"],
        "name": user.get("name") or "",
        "team": user.get("team") or "",
        "role": user.get("role") or "student",
        "sponsor": user.get("sponsor") or "",
        "points": int(user.get("points") or 0),
        "used_state5": bool(user.get("used_state5")),
        "used_state1": bool(user.get("used_state1")),
    }


def token_from_headers(headers) -> str:
    auth = headers.get("authorization") or headers.get("Authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    return ""


def user_from_token(token: str):
    if not token:
        return None
    with _lock:
        data = _load()
        session = data["sessions"].get(token)
        if not session:
            return None
        if session.get("exp", 0) < time.time():
            data["sessions"].pop(token, None)
            _dump(data)
            return None
        user = data["users"].get(session.get("username"))
        if not user:
            return None
        return deepcopy(user)


def login(username: str, password: str, name: str, team: str) -> dict:
    username = (username or "").strip()
    password = password or ""
    name = (name or "").strip()
    team = (team or "").strip()
    if not username or not password:
        raise ValueError("نام کاربری و رمز عبور لازم است.")
    with _lock:
        data = _load()
        user = data["users"].get(username)
        if not user or not _verify_password(password, user["password"]):
            raise ValueError("نام کاربری یا رمز عبور نادرست است.")
        if not is_staff(user):
            if not name:
                raise ValueError("نام Voter را وارد کنید.")
            if not team:
                raise ValueError("نام تیم را وارد کنید.")
            user["name"] = name
            user["team"] = team
        elif name:
            user["name"] = name
        token = secrets.token_urlsafe(32)
        data["sessions"][token] = {
            "username": username,
            "exp": time.time() + SESSION_TTL,
        }
        _dump(data)
        return {"token": token, "user": _public_user(user)}


def logout(token: str) -> None:
    if not token:
        return
    with _lock:
        data = _load()
        data["sessions"].pop(token, None)
        _dump(data)


def create_student(actor: dict, username: str, password: str) -> dict:
    if not is_staff(actor):
        raise PermissionError("فقط Mentor یا Admin می‌تواند حساب Voter بسازد.")
    username = (username or "").strip()
    password = password or ""
    if not USERNAME_RE.match(username):
        raise ValueError("نام کاربری باید ۲ تا ۳۲ نویسه انگلیسی، عدد یا ._- باشد.")
    if len(password) < 4:
        raise ValueError("رمز عبور حداقل ۴ نویسه باشد.")
    with _lock:
        data = _load()
        students = [u for u in data["users"].values() if u.get("role") == "student"]
        if len(students) >= MAX_STUDENTS:
            raise ValueError(f"حداکثر {MAX_STUDENTS} حساب Voter مجاز است.")
        if is_admin(actor):
            mine = [u for u in students if u.get("sponsor") == actor["username"]]
            if len(mine) >= STUDENTS_PER_ADMIN:
                raise ValueError(f"هر Mentor حداکثر {STUDENTS_PER_ADMIN} Voter دارد.")
        if username in data["users"]:
            raise ValueError("این نام کاربری قبلاً ساخته شده است.")
        data["users"][username] = {
            "username": username,
            "password": _hash_password(password),
            "role": "student",
            "name": "",
            "team": "",
            "points": 0,
            "used_state5": False,
            "used_state1": False,
            "sponsor": actor["username"],
            "unlocked": ["vote"],
        }
        _bump(data)
        _dump(data)
        return _public_user(data["users"][username])


def create_admin(actor: dict, username: str, password: str) -> dict:
    if not is_owner(actor):
        raise PermissionError("فقط Admin می‌تواند Mentor بسازد.")
    username = (username or "").strip()
    password = password or ""
    if not USERNAME_RE.match(username):
        raise ValueError("نام کاربری باید ۲ تا ۳۲ نویسه انگلیسی، عدد یا ._- باشد.")
    if len(password) < 4:
        raise ValueError("رمز عبور حداقل ۴ نویسه باشد.")
    with _lock:
        data = _load()
        admins = [u for u in data["users"].values() if u.get("role") == "admin"]
        if len(admins) >= MAX_ADMINS:
            raise ValueError(f"حداکثر {MAX_ADMINS} Mentor مجاز است.")
        if username in data["users"]:
            raise ValueError("این نام کاربری قبلاً ساخته شده است.")
        data["users"][username] = {
            "username": username,
            "password": _hash_password(password),
            "role": "admin",
            "name": "",
            "team": "",
            "points": 0,
            "used_state5": False,
            "used_state1": False,
            "sponsor": actor["username"],
            "unlocked": list(PANEL_IDS),
        }
        _bump(data)
        _dump(data)
        return _public_user(data["users"][username])


def delete_student(actor: dict, username: str) -> None:
    if not is_staff(actor):
        raise PermissionError("اجازه حذف ندارید.")
    username = (username or "").strip()
    with _lock:
        data = _load()
        user = data["users"].get(username)
        if not user:
            raise ValueError("حساب پیدا نشد.")
        if user.get("role") == "owner":
            raise ValueError("Admin را نمی‌توان حذف کرد.")
        if user.get("role") == "admin":
            if not is_owner(actor):
                raise PermissionError("فقط Admin می‌تواند Mentor را حذف کند.")
            for other in data["users"].values():
                if other.get("sponsor") == username:
                    other["sponsor"] = actor["username"]
        elif is_admin(actor) and user.get("sponsor") != actor["username"]:
            raise PermissionError("فقط Voterهای خودتان را می‌توانید حذف کنید.")
        data["users"].pop(username, None)
        data["votes"].pop(username, None)
        data["ideas"] = [idea for idea in data["ideas"] if idea.get("username") != username]
        data["state1_ideas"] = [idea for idea in data.get("state1_ideas") or [] if idea.get("username") != username]
        data["sessions"] = {
            tok: sess for tok, sess in data["sessions"].items() if sess.get("username") != username
        }
        _bump(data)
        _dump(data)


def list_users(actor: dict) -> list:
    if not is_staff(actor):
        raise PermissionError("فقط Mentor یا Admin.")
    with _lock:
        data = _load()
        users = []
        for u in data["users"].values():
            if is_owner(actor) or u["username"] == actor["username"] or u.get("sponsor") == actor["username"]:
                users.append(_public_user(u))
        users.sort(key=lambda u: ({"owner": 0, "admin": 1}.get(u["role"], 2), u["username"]))
        return users


def _related_ids(panel_id: str, hiding: bool = False) -> list:
    ids = [panel_id]
    if panel_id.startswith("s4-"):
        ids.append("s4")
    if panel_id.startswith("s6-"):
        ids.append("s6")
    if hiding and panel_id == "s4":
        ids.extend([p for p in PANEL_IDS if p.startswith("s4")])
    if hiding and panel_id == "s6":
        ids.extend([p for p in PANEL_IDS if p.startswith("s6")])
    return list(dict.fromkeys(ids))


def _effective_unlocked(data: dict, user: dict) -> list:
    shown = set(data.get("unlocked") or ["vote"]) | set(user.get("unlocked") or ["vote"])
    shown -= set(user.get("hidden") or [])
    return sorted(shown)


def _audience_unlocked(data: dict, actor: dict) -> list:
    if is_owner(actor):
        return list(data.get("unlocked") or ["vote"])
    if is_admin(actor):
        shown = set()
        found = False
        for user in data["users"].values():
            if user.get("role") == "student" and user.get("sponsor") == actor["username"]:
                found = True
                shown.update(_effective_unlocked(data, user))
        if not found:
            shown.update(data.get("unlocked") or ["vote"])
        return sorted(shown)
    return _effective_unlocked(data, actor)


def _grant_user(user: dict, ids) -> None:
    unlocked = list(user.get("unlocked") or ["vote"])
    hidden = list(user.get("hidden") or [])
    for item in ids:
        if item not in unlocked:
            unlocked.append(item)
        if item in hidden:
            hidden.remove(item)
    user["unlocked"] = unlocked
    user["hidden"] = hidden


def _revoke_user(user: dict, ids) -> None:
    drop = set(ids)
    user["unlocked"] = [item for item in (user.get("unlocked") or ["vote"]) if item not in drop]
    hidden = list(user.get("hidden") or [])
    for item in ids:
        if item not in hidden:
            hidden.append(item)
    user["hidden"] = hidden


def unlock_panel(actor: dict, panel_id: str) -> list:
    if not is_staff(actor):
        raise PermissionError("فقط Mentor یا Admin می‌تواند پنل باز کند.")
    panel_id = (panel_id or "").strip()
    if not panel_id:
        raise ValueError("شناسه پنل لازم است.")
    extras = _related_ids(panel_id, hiding=False)
    with _lock:
        data = _load()
        if is_owner(actor):
            unlocked = list(data.get("unlocked") or [])
            for item in extras:
                if item not in unlocked:
                    unlocked.append(item)
            data["unlocked"] = unlocked
            for user in data["users"].values():
                if user.get("role") == "student":
                    _grant_user(user, extras)
        else:
            for user in data["users"].values():
                if user.get("role") == "student" and user.get("sponsor") == actor["username"]:
                    _grant_user(user, extras)
        _bump(data)
        _dump(data)
        return _audience_unlocked(data, actor)


def hide_panel(actor: dict, panel_id: str) -> list:
    if not is_staff(actor):
        raise PermissionError("فقط Mentor یا Admin می‌تواند پنل را مخفی کند.")
    panel_id = (panel_id or "").strip()
    if not panel_id:
        raise ValueError("شناسه پنل لازم است.")
    extras = _related_ids(panel_id, hiding=True)
    with _lock:
        data = _load()
        if is_owner(actor):
            data["unlocked"] = [item for item in (data.get("unlocked") or []) if item not in extras]
            for user in data["users"].values():
                if user.get("role") == "student":
                    _revoke_user(user, extras)
        else:
            for user in data["users"].values():
                if user.get("role") == "student" and user.get("sponsor") == actor["username"]:
                    _revoke_user(user, extras)
        _bump(data)
        _dump(data)
        return _audience_unlocked(data, actor)


def set_vote(user: dict, rank: str) -> dict:
    rank = (rank or "").strip()
    parts = [p for p in rank.replace("≻", ">").split(">") if p.strip()]
    parts = [p.strip().upper() for p in parts]
    if sorted(parts) != ["A", "B", "C"]:
        raise ValueError("رتبه‌بندی باید دقیقاً A و B و C باشد.")
    with _lock:
        data = _load()
        if data.get("vote_revealed") and not is_staff(user):
            raise ValueError("رأی‌گیری تمام شده و دیگر نمی‌توان رأی را عوض کرد.")
        data["votes"][user["username"]] = {
            "rank": ">".join(parts),
            "name": user.get("name") or user["username"],
            "team": user.get("team") or "",
        }
        _bump(data)
        _dump(data)
        return data["votes"][user["username"]]


def present_votes(actor: dict) -> dict:
    if not is_staff(actor):
        raise PermissionError("فقط Mentor یا Admin می‌تواند نتیجه را نشان بدهد.")
    with _lock:
        data = _load()
        if not data.get("vote_display"):
            data["vote_display"] = _fake_display_votes(data.get("votes") or {})
        data["vote_revealed"] = True
        _bump(data)
        _dump(data)
        return {"vote_revealed": True, "votes": list(data["vote_display"])}


def set_arrows(admin: dict, profiles) -> list:
    if admin.get("role") != "admin":
        raise PermissionError("فقط Mentor یا Admin می‌تواند قضیه ارو را عوض کند.")
    if not isinstance(profiles, list) or len(profiles) != 3:
        raise ValueError("پروفایل‌های ارو نامعتبر است.")
    cleaned = []
    for profile in profiles:
        if not isinstance(profile, list) or len(profile) != 9:
            raise ValueError("هر پروفایل باید ۹ رأی‌دهنده داشته باشد.")
        row = []
        for voter in profile:
            if not isinstance(voter, dict):
                raise ValueError("رأی‌دهنده نامعتبر است.")
            rank = [str(x).strip().upper() for x in (voter.get("rank") or [])]
            if sorted(rank) != ["A", "B", "C"]:
                raise ValueError("رتبه هر رأی‌دهنده باید A و B و C باشد.")
            row.append({"id": int(voter.get("id") or 0), "rank": rank})
        cleaned.append(row)
    with _lock:
        data = _load()
        data["arrows"] = cleaned
        _bump(data)
        _dump(data)
        return cleaned


def reset_arrows(admin: dict) -> list:
    return set_arrows(admin, default_arrows())


def _score_prompt(prompt: str) -> tuple:
    criteria = evaluate_criteria(prompt)
    valid = criteria.get("valid", True)
    if not valid:
        criteria = {key: False for key in CRITERIA_KEYS}
        criteria["valid"] = False
        return criteria, 0
    passed = sum(1 for key in CRITERIA_KEYS if criteria.get(key))
    return criteria, passed * POINTS_PER_CRITERION


def submit_idea(user: dict, prompt: str) -> dict:
    prompt = (prompt or "").strip()
    if not prompt:
        raise ValueError("prompt is required.")
    with _lock:
        data = _load()
        stored = data["users"].get(user["username"])
        if not stored:
            raise ValueError("حساب پیدا نشد.")
        if stored.get("role") == "student" and stored.get("used_state5"):
            raise ValueError("هر نفر فقط یک بار می‌تواند روش خود را بفرستد.")

    criteria, points = _score_prompt(prompt)
    idea = {
        "id": secrets.token_hex(8),
        "username": user["username"],
        "name": user.get("name") or user["username"],
        "team": user.get("team") or "",
        "text": prompt,
        "criteria": criteria,
        "examples": [],
        "examplesLoaded": False,
        "points": points,
    }
    with _lock:
        data = _load()
        stored = data["users"].get(user["username"])
        if not stored:
            raise ValueError("حساب پیدا نشد.")
        if stored.get("role") == "student":
            if stored.get("used_state5"):
                raise ValueError("هر نفر فقط یک بار می‌تواند روش خود را بفرستد.")
            stored["used_state5"] = True
            stored["points"] = int(stored.get("points") or 0) + points
        idea["name"] = stored.get("name") or idea["name"]
        idea["team"] = stored.get("team") or idea["team"]
        idea["class_id"] = _class_key(stored)
        data["ideas"].append(idea)
        _bump(data)
        _dump(data)
        idea = deepcopy(idea)
        idea["used_state5"] = True
        idea["total_points"] = int(stored.get("points") or points)
        return idea


def add_examples(user: dict, idea_id: str = "", prompt: str = "", criteria=None) -> dict:
    with _lock:
        data = _load()
        idea = None
        if idea_id:
            idea = next((item for item in data["ideas"] if item.get("id") == idea_id), None)
        if idea is None and prompt:
            idea = next(
                (
                    item
                    for item in reversed(data["ideas"])
                    if item.get("username") == user["username"] and item.get("text") == prompt
                ),
                None,
            )
        if idea is None:
            raise ValueError("ابتدا روش را ارزیابی کنید.")
        stored = data["users"].get(user["username"]) or user
        if _idea_class(data, idea) != _class_key(stored):
            raise PermissionError("این ایده مال کلاس شما نیست.")
        if stored.get("role") == "student" and idea.get("username") != stored.get("username"):
            raise PermissionError("فقط برای روش خودتان می‌توانید مثال بگیرید.")
        text = idea["text"]
        crit = normalize_criteria(idea.get("criteria") or criteria)

    examples = generate_examples(text, crit)
    with _lock:
        data = _load()
        for item in data["ideas"]:
            if item.get("id") == idea.get("id"):
                item["examples"] = examples
                item["examplesLoaded"] = True
                idea = deepcopy(item)
                break
        _bump(data)
        _dump(data)
    return idea


def set_state1_idea(user: dict, text: str) -> dict:
    text = (text or "").strip()
    if not text:
        raise ValueError("ایده خالی است.")
    with _lock:
        data = _load()
        stored = data["users"].get(user["username"])
        if not stored:
            raise ValueError("حساب پیدا نشد.")
        ideas = list(data.get("state1_ideas") or [])
        existing = next((item for item in ideas if item.get("username") == user["username"]), None)
        if existing and stored.get("role") == "student":
            raise ValueError("هر نفر فقط یک ایده می‌تواند بفرستد.")
        idea = {
            "id": secrets.token_hex(8),
            "username": user["username"],
            "name": stored.get("name") or user["username"],
            "team": stored.get("team") or "",
            "text": text,
            "class_id": _class_key(stored),
        }
        if existing:
            existing.update(idea)
            idea = existing
        else:
            ideas.append(idea)
        data["state1_ideas"] = ideas
        stored["used_state1"] = True
        _bump(data)
        _dump(data)
        return deepcopy(idea)


def process_state1_idea(actor: dict, idea_id: str) -> dict:
    if not is_staff(actor):
        raise PermissionError("فقط Mentor یا Admin می‌تواند ایده استیت ۱ را برای رأی‌دهنده‌ها ارزیابی کند.")
    idea_id = (idea_id or "").strip()
    if not idea_id:
        raise ValueError("ایده مشخص نشده.")

    with _lock:
        data = _load()
        stored = data["users"].get(actor["username"])
        if not stored:
            raise ValueError("حساب پیدا نشد.")
        src = next((item for item in (data.get("state1_ideas") or []) if item.get("id") == idea_id), None)
        if src is None:
            raise ValueError("ایده استیت ۱ پیدا نشد.")
        if _idea_class(data, src) != _class_key(stored):
            raise PermissionError("این ایده مال کلاس شما نیست.")
        if src.get("evaluated_id"):
            existing = next((item for item in data.get("ideas") or [] if item.get("id") == src["evaluated_id"]), None)
            if existing:
                idea = deepcopy(existing)
                author = data["users"].get(existing.get("username") or "")
                idea["used_state5"] = True
                idea["total_points"] = int((author or {}).get("points") or existing.get("points") or 0)
                return idea
        text = (src.get("text") or "").strip()
        if not text:
            raise ValueError("متن ایده خالی است.")
        author_name = src.get("username") or ""
        author = data["users"].get(author_name)
        if author and author.get("role") == "student" and author.get("used_state5"):
            raise ValueError("این رأی‌دهنده قبلاً در استیت ۵ روش فرستاده است.")
        src_name = src.get("name") or author_name
        src_team = src.get("team") or ""
        src_class = src.get("class_id") or _idea_class(data, src)

    criteria, points = _score_prompt(text)
    idea = {
        "id": secrets.token_hex(8),
        "username": author_name,
        "name": src_name,
        "team": src_team,
        "text": text,
        "criteria": criteria,
        "examples": [],
        "examplesLoaded": False,
        "points": points,
        "from_state1_id": idea_id,
        "class_id": src_class,
    }
    with _lock:
        data = _load()
        stored = data["users"].get(actor["username"])
        if not stored:
            raise ValueError("حساب پیدا نشد.")
        src = next((item for item in (data.get("state1_ideas") or []) if item.get("id") == idea_id), None)
        if src is None:
            raise ValueError("ایده استیت ۱ پیدا نشد.")
        if _idea_class(data, src) != _class_key(stored):
            raise PermissionError("این ایده مال کلاس شما نیست.")
        if src.get("evaluated_id"):
            existing = next((item for item in data.get("ideas") or [] if item.get("id") == src["evaluated_id"]), None)
            if existing:
                idea = deepcopy(existing)
                author = data["users"].get(existing.get("username") or "")
                idea["used_state5"] = True
                idea["total_points"] = int((author or {}).get("points") or existing.get("points") or 0)
                return idea
        author = data["users"].get(author_name)
        if author and author.get("role") == "student" and author.get("used_state5"):
            raise ValueError("این رأی‌دهنده قبلاً در استیت ۵ روش فرستاده است.")
        if author:
            idea["name"] = author.get("name") or idea["name"]
            idea["team"] = author.get("team") or idea["team"]
            idea["class_id"] = _class_key(author)
            if author.get("role") == "student":
                author["used_state5"] = True
                author["points"] = int(author.get("points") or 0) + points
        src["evaluated_id"] = idea["id"]
        src["processed"] = True
        data.setdefault("ideas", []).append(idea)
        _bump(data)
        _dump(data)
        idea = deepcopy(idea)
        idea["used_state5"] = True
        idea["total_points"] = int((author or {}).get("points") or points)
        return idea


def _can_delete_idea(actor: dict, idea: dict, data: dict) -> bool:
    if not idea:
        return False
    if _idea_class(data, idea) != _class_key(actor):
        return False
    if is_staff(actor):
        return True
    return (idea.get("username") or "") == (actor.get("username") or "")


def _drop_state5(data: dict, idea_id: str) -> None:
    idea = next((item for item in data.get("ideas") or [] if item.get("id") == idea_id), None)
    if not idea:
        return
    author = data["users"].get(idea.get("username") or "")
    if author and author.get("role") == "student":
        author["used_state5"] = False
        author["points"] = max(0, int(author.get("points") or 0) - int(idea.get("points") or 0))
    for src in data.get("state1_ideas") or []:
        if src.get("evaluated_id") == idea_id or src.get("id") == idea.get("from_state1_id"):
            src.pop("evaluated_id", None)
            src["processed"] = False
    data["ideas"] = [item for item in (data.get("ideas") or []) if item.get("id") != idea_id]


def delete_idea(actor: dict, idea_id: str, source: str = "") -> dict:
    idea_id = (idea_id or "").strip()
    source = (source or "").strip().lower()
    if not idea_id:
        raise ValueError("ایده مشخص نشده.")
    with _lock:
        data = _load()
        stored = data["users"].get(actor["username"])
        if not stored:
            raise ValueError("حساب پیدا نشد.")
        s1 = next((item for item in data.get("state1_ideas") or [] if item.get("id") == idea_id), None)
        s5 = next((item for item in data.get("ideas") or [] if item.get("id") == idea_id), None)
        if source == "state1":
            target, kind = s1, "state1"
        elif source in ("state5", "ideas"):
            target, kind = s5, "state5"
        elif s1:
            target, kind = s1, "state1"
        else:
            target, kind = s5, "state5"
        if not target:
            raise ValueError("ایده پیدا نشد.")
        if not _can_delete_idea(stored, target, data):
            raise PermissionError("اجازه حذف این ایده را ندارید.")
        if kind == "state1":
            linked = target.get("evaluated_id") or ""
            author = data["users"].get(target.get("username") or "")
            if author:
                author["used_state1"] = False
            data["state1_ideas"] = [
                item for item in (data.get("state1_ideas") or []) if item.get("id") != idea_id
            ]
            if linked:
                _drop_state5(data, linked)
        else:
            _drop_state5(data, idea_id)
        _bump(data)
        _dump(data)
        return {"ok": True, "source": kind, "me": _public_user(stored)}


def reset_workshop(actor: dict) -> None:
    if not is_staff(actor):
        raise PermissionError("فقط Mentor یا Admin.")
    with _lock:
        data = _load()
        if is_owner(actor):
            data["unlocked"] = ["vote"]
            data["vote_revealed"] = False
            data["vote_display"] = []
            for user in data["users"].values():
                if user.get("role") == "student":
                    user["unlocked"] = ["vote"]
                    user["hidden"] = []
        else:
            mine = actor["username"]
            for user in data["users"].values():
                if user.get("role") == "student" and user.get("sponsor") == mine:
                    user["unlocked"] = ["vote"]
                    user["hidden"] = []
        _bump(data)
        _dump(data)


def snapshot(user: dict) -> dict:
    with _lock:
        data = _load()
        stored = data["users"].get(user["username"]) or user
        votes = []
        if data.get("vote_revealed"):
            votes = list(data.get("vote_display") or [])
            if not votes:
                data["vote_display"] = _fake_display_votes(data.get("votes") or {})
                votes = list(data["vote_display"])
                _bump(data)
                _dump(data)
            votes = list(data.get("vote_display") or [])
        unlocked = _audience_unlocked(data, stored)
        return {
            "version": data.get("version") or 0,
            "me": _public_user(stored),
            "unlocked": unlocked,
            "vote_revealed": bool(data.get("vote_revealed")),
            "my_vote": (data.get("votes") or {}).get(user["username"]),
            "votes": votes,
            "ideas": _class_ideas(data, stored, data.get("ideas") or []),
            "state1_ideas": _class_ideas(data, stored, data.get("state1_ideas") or []),
            "store": store_kind(),
            "live": live_classroom_ok(),
        }
