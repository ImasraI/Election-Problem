import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
from copy import deepcopy
from pathlib import Path

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

MAX_STUDENTS = 100
SESSION_TTL = 60 * 60 * 16
PBKDF2_ROUNDS = 120_000
CRITERIA_KEYS = ["AAW", "CWC", "UNAN", "MONO", "IIA"]
POINTS_PER_CRITERION = 10
USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{2,32}$")

_lock = threading.Lock()

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


def _blank() -> dict:
    admin_password = os.environ.get("ADMIN_PASSWORD") or "admin"
    return {
        "version": 1,
        "unlocked": ["vote"],
        "vote_revealed": False,
        "votes": {},
        "ideas": [],
        "arrows": default_arrows(),
        "users": {
            "admin": {
                "username": "admin",
                "password": _hash_password(admin_password),
                "role": "admin",
                "name": "ادمین",
                "team": "",
                "points": 0,
                "used_state5": False,
            }
        },
        "sessions": {},
    }


def _load() -> dict:
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
    data.setdefault("version", 1)
    data.setdefault("unlocked", ["vote"])
    data.setdefault("vote_revealed", False)
    data.setdefault("votes", {})
    data.setdefault("ideas", [])
    data.setdefault("arrows", default_arrows())
    data.setdefault("users", {})
    data.setdefault("sessions", {})
    if "admin" not in data["users"]:
        data["users"]["admin"] = _blank()["users"]["admin"]
    if "vote" not in data["unlocked"]:
        data["unlocked"] = ["vote"] + list(data["unlocked"])
    return data


def _dump(data: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = DATA_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(DATA_PATH)


def _bump(data: dict) -> None:
    data["version"] = int(data.get("version") or 0) + 1


def _public_user(user: dict) -> dict:
    return {
        "username": user["username"],
        "name": user.get("name") or "",
        "team": user.get("team") or "",
        "role": user.get("role") or "student",
        "points": int(user.get("points") or 0),
        "used_state5": bool(user.get("used_state5")),
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
        if user.get("role") != "admin":
            if not name:
                raise ValueError("نام دانش‌آموز را وارد کنید.")
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


def create_student(admin: dict, username: str, password: str) -> dict:
    if admin.get("role") != "admin":
        raise PermissionError("فقط ادمین می‌تواند حساب بسازد.")
    username = (username or "").strip()
    password = password or ""
    if not USERNAME_RE.match(username):
        raise ValueError("نام کاربری باید ۲ تا ۳۲ نویسه انگلیسی، عدد یا ._- باشد.")
    if len(password) < 4:
        raise ValueError("رمز عبور حداقل ۴ نویسه باشد.")
    with _lock:
        data = _load()
        students = [u for u in data["users"].values() if u.get("role") != "admin"]
        if len(students) >= MAX_STUDENTS:
            raise ValueError(f"حداکثر {MAX_STUDENTS} حساب دانش‌آموز مجاز است.")
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
        }
        _bump(data)
        _dump(data)
        return _public_user(data["users"][username])


def delete_student(admin: dict, username: str) -> None:
    if admin.get("role") != "admin":
        raise PermissionError("فقط ادمین می‌تواند حساب حذف کند.")
    username = (username or "").strip()
    with _lock:
        data = _load()
        user = data["users"].get(username)
        if not user:
            raise ValueError("حساب پیدا نشد.")
        if user.get("role") == "admin":
            raise ValueError("حساب ادمین را نمی‌توان حذف کرد.")
        data["users"].pop(username, None)
        data["votes"].pop(username, None)
        data["ideas"] = [idea for idea in data["ideas"] if idea.get("username") != username]
        data["sessions"] = {
            tok: sess for tok, sess in data["sessions"].items() if sess.get("username") != username
        }
        _bump(data)
        _dump(data)


def list_users(admin: dict) -> list:
    if admin.get("role") != "admin":
        raise PermissionError("فقط ادمین.")
    with _lock:
        data = _load()
        users = [_public_user(u) for u in data["users"].values()]
        users.sort(key=lambda u: (0 if u["role"] == "admin" else 1, u["username"]))
        return users


def unlock_panel(admin: dict, panel_id: str) -> list:
    if admin.get("role") != "admin":
        raise PermissionError("فقط ادمین می‌تواند پنل باز کند.")
    panel_id = (panel_id or "").strip()
    if not panel_id:
        raise ValueError("شناسه پنل لازم است.")
    with _lock:
        data = _load()
        unlocked = list(data.get("unlocked") or [])
        if panel_id not in unlocked:
            unlocked.append(panel_id)
        if panel_id.startswith("s4-") and "s4" not in unlocked:
            unlocked.append("s4")
        if panel_id.startswith("s6-") and "s6" not in unlocked:
            unlocked.append("s6")
        data["unlocked"] = unlocked
        _bump(data)
        _dump(data)
        return unlocked


def set_vote(user: dict, rank: str) -> dict:
    rank = (rank or "").strip()
    parts = [p for p in rank.replace("≻", ">").split(">") if p.strip()]
    parts = [p.strip().upper() for p in parts]
    if sorted(parts) != ["A", "B", "C"]:
        raise ValueError("رتبه‌بندی باید دقیقاً A و B و C باشد.")
    with _lock:
        data = _load()
        if data.get("vote_revealed") and user.get("role") != "admin":
            raise ValueError("رأی‌گیری تمام شده و دیگر نمی‌توان رأی را عوض کرد.")
        data["votes"][user["username"]] = {
            "rank": ">".join(parts),
            "name": user.get("name") or user["username"],
            "team": user.get("team") or "",
        }
        _bump(data)
        _dump(data)
        return data["votes"][user["username"]]


def present_votes(admin: dict) -> dict:
    if admin.get("role") != "admin":
        raise PermissionError("فقط ادمین می‌تواند نتیجه را نشان بدهد.")
    with _lock:
        data = _load()
        data["vote_revealed"] = True
        _bump(data)
        _dump(data)
        return {"vote_revealed": True, "votes": list(data["votes"].values())}


def set_arrows(admin: dict, profiles) -> list:
    if admin.get("role") != "admin":
        raise PermissionError("فقط ادمین می‌تواند قضیه ارو را عوض کند.")
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


def submit_idea(user: dict, prompt: str) -> dict:
    prompt = (prompt or "").strip()
    if not prompt:
        raise ValueError("prompt is required.")
    with _lock:
        data = _load()
        stored = data["users"].get(user["username"])
        if not stored:
            raise ValueError("حساب پیدا نشد.")
        if stored.get("role") != "admin" and stored.get("used_state5"):
            raise ValueError("هر نفر فقط یک بار می‌تواند روش خود را بفرستد.")

    criteria = evaluate_criteria(prompt)
    passed = sum(1 for key in CRITERIA_KEYS if criteria.get(key))
    points = passed * POINTS_PER_CRITERION
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
        if stored.get("role") != "admin":
            if stored.get("used_state5"):
                raise ValueError("هر نفر فقط یک بار می‌تواند روش خود را بفرستد.")
            stored["used_state5"] = True
            stored["points"] = int(stored.get("points") or 0) + points
        idea["name"] = stored.get("name") or idea["name"]
        idea["team"] = stored.get("team") or idea["team"]
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
        if user.get("role") != "admin" and idea.get("username") != user["username"]:
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


def reset_workshop(admin: dict) -> None:
    if admin.get("role") != "admin":
        raise PermissionError("فقط ادمین.")
    with _lock:
        data = _load()
        data["unlocked"] = ["vote"]
        data["vote_revealed"] = False
        data["votes"] = {}
        data["ideas"] = []
        data["arrows"] = default_arrows()
        for user in data["users"].values():
            if user.get("role") != "admin":
                user["points"] = 0
                user["used_state5"] = False
        _bump(data)
        _dump(data)


def snapshot(user: dict) -> dict:
    with _lock:
        data = _load()
        stored = data["users"].get(user["username"]) or user
        is_admin = stored.get("role") == "admin"
        votes = []
        if data.get("vote_revealed") or is_admin:
            votes = list(data["votes"].values())
        return {
            "version": data.get("version") or 0,
            "me": _public_user(stored),
            "unlocked": list(data.get("unlocked") or ["vote"]),
            "vote_revealed": bool(data.get("vote_revealed")),
            "my_vote": (data.get("votes") or {}).get(user["username"]),
            "votes": votes,
            "ideas": deepcopy(data.get("ideas") or []),
            "arrows": deepcopy(data.get("arrows") or default_arrows()),
        }
