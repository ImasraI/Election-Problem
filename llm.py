import json
import os
import re
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import requests

# --- DeepSeek V4 (Free) via OrcaRouter ---------------------------------
OPENAI_API_BASE = "https://api.orcarouter.ai/v1"
OPENAI_CHAT_URL = f"{OPENAI_API_BASE}/chat/completions"
MODEL_NAME = "deepseek/deepseek-v4-flash-free"

HOST = "0.0.0.0"
PORT = 8765
ROOT = Path(__file__).resolve().parent
ENV_PATH = ROOT / ".env"
PLACEHOLDER_KEYS = {"", "your_orcarouter_api_key_here", "changeme"}


def _clean_env_value(value: str) -> str:
    value = (value or "").strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    return value.strip()


def _is_real_key(key: str) -> bool:
    return bool(key) and key.lower() not in PLACEHOLDER_KEYS


def read_env_file_key(path: Path) -> str:
    if not path.is_file():
        return ""
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        if name.strip() == "ORCAROUTER_API_KEY":
            return _clean_env_value(value)
    return ""


def save_env_key(key: str) -> None:
    ENV_PATH.write_text(
        "# Local OrcaRouter key. Do not commit this file.\n"
        f"ORCAROUTER_API_KEY={key}\n",
        encoding="utf-8",
    )


def prompt_for_api_key() -> str:
    print("No API key found in .env.")
    print("This app needs an OrcaRouter API key.")
    print("Create one at https://orcarouter.ai then paste it below.\n")
    try:
        key = _clean_env_value(input("ORCAROUTER_API_KEY: "))
    except EOFError:
        key = ""
    if not _is_real_key(key):
        print("No key entered.", file=sys.stderr)
        sys.exit(1)
    save_env_key(key)
    print("Saved the key to .env\n", flush=True)
    return key


def require_api_key() -> str:
    key = read_env_file_key(ENV_PATH)
    if not _is_real_key(key):
        key = prompt_for_api_key()
    os.environ["ORCAROUTER_API_KEY"] = key
    return key


API_KEY = require_api_key()

CRITERIA_KEYS = ["AAW", "CWC", "UNAN", "MONO", "IIA"]

# Chart request: only the five true/false flags. No analysis, no examples.
CRITERIA_SYSTEM_PROMPT = """
You are an expert in social choice theory. The user describes a voting
method in Persian. Judge whether it GENERALLY satisfies each of five
criteria: AAW, CWC, UNAN, MONO, IIA.

Short definitions:
- AAW: always produces at least one winner (ties ok only if a tie-break exists).
- CWC: if a Condorcet winner exists, the method always elects them.
- UNAN: if everyone ranks A above B, B cannot win.
- MONO: ranking a winner higher must not make that winner lose.
- IIA: A vs B must not flip only because of a third candidate C.
  Cardinal/independent scores (approval, 0-10 ratings) typically satisfy IIA.
  Rank/positional scores (plurality, Borda, "distinct scores 1 to N") violate IIA.

Calibration (still reason about THIS method): plurality fails CWC and IIA;
Borda fails CWC and IIA; IRV/Hare fails MONO, CWC, IIA; approval usually
passes IIA.

Output ONLY a valid json object with exactly these five boolean keys.
true = the criterion holds in general. false = it can be violated.
No markdown, no extra keys, no explanation.

Example of correct json:
{"AAW": true, "CWC": false, "UNAN": true, "MONO": true, "IIA": false}
"""

EXAMPLES_SYSTEM_PROMPT = """
You will be given:
1. The user's voting method (Persian).
2. The list of FAILED criteria (those judged false / نقض), already in order.

For EACH failed criterion, produce one concrete numerical counterexample
that shows this specific method violating that rule. Use candidates A, B, C
and explicit voter counts. Do not invent examples for criteria that hold.

Output ONLY a valid JSON object with this shape (no markdown, no extra keys):

{
  "examples": [
    {
      "rule": "CWC",
      "title": "short Persian title",
      "ballots": ["۳ نفر: A ≻ B ≻ C", "۲ نفر: B ≻ C ≻ A"],
      "result": "what this method elects, and how that contradicts the criterion",
      "why": "one or two Persian sentences explaining the violation"
    }
  ]
}

Put examples in this order: AAW, CWC, UNAN, MONO, IIA (skip any that
are not in the failed list). For MONO/IIA include before and after ballots
in the ballots array. All title/result/why/ballot text must be Persian.
"""


def _flatten_content(content) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or ""))
        return "\n".join(parts).strip()
    return str(content).strip()


def _message_text(data) -> str:
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("No choices in response.")
    msg = choices[0].get("message") or {}
    parsed = msg.get("parsed")
    if isinstance(parsed, dict):
        return json.dumps(parsed, ensure_ascii=False)
    text = _flatten_content(msg.get("content"))
    if text:
        return text
    alt = _flatten_content(choices[0].get("text"))
    if alt:
        return alt
    # Thinking models sometimes leave content empty and put the answer
    # in reasoning_content after burning the max_tokens budget.
    for key in ("reasoning_content", "reasoning"):
        extra = _flatten_content(msg.get(key))
        if extra:
            return extra
    return ""


def _chat(system_prompt: str, user_content: str, *, json_mode: bool, max_tokens: int) -> str:
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": MODEL_NAME,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.2,
        "top_p": 0.9,
        "stream": False,
        "max_tokens": max_tokens,
        "max_completion_tokens": max_tokens,
        # DeepSeek V4 thinks by default; those tokens count against
        # max_tokens, which left content empty with a 200-token cap.
        "thinking": {"type": "disabled"},
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    last_text = ""
    attempts = 2
    for attempt in range(attempts):
        body = dict(payload)
        if attempt == 1:
            body.pop("response_format", None)
            body.pop("thinking", None)
        try:
            response = requests.post(OPENAI_CHAT_URL, headers=headers, json=body, timeout=300)
            if response.status_code in (400, 422) and (
                "thinking" in body or "max_completion_tokens" in body or "response_format" in body
            ):
                for drop in ("thinking", "max_completion_tokens", "response_format"):
                    body.pop(drop, None)
                response = requests.post(OPENAI_CHAT_URL, headers=headers, json=body, timeout=300)
            response.raise_for_status()
        except requests.exceptions.ConnectionError:
            raise RuntimeError(f"Cannot connect to OrcaRouter at {OPENAI_CHAT_URL}.")
        except requests.exceptions.Timeout:
            raise RuntimeError("Request timed out.")
        except requests.exceptions.HTTPError as e:
            detail = ""
            response = getattr(e, "response", None)
            if response is not None:
                try:
                    detail = response.text
                except Exception:
                    pass
            raise RuntimeError(f"HTTP error from OrcaRouter: {e}. {detail}")
        except requests.exceptions.RequestException as e:
            raise RuntimeError(str(e))

        data = response.json()
        last_text = _message_text(data)
        if last_text:
            return last_text
        choice = (data.get("choices") or [{}])[0]
        sys.stderr.write(
            "empty model content attempt=%s finish=%s usage=%s\n"
            % (attempt + 1, choice.get("finish_reason"), data.get("usage"))
        )
    return last_text


def _as_bool(val) -> bool:
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        return bool(val)
    s = str(val or "").strip().lower()
    if s in ("true", "1", "yes", "hold", "holds") or "برقرار" in s:
        return True
    if s in ("false", "0", "no") or "نقض" in s:
        return False
    return bool(val)


def parse_criteria(text: str) -> dict:
    raw = (text or "").strip()
    if not raw:
        raise ValueError("Empty model response.")
    match = re.search(r"\{[\s\S]*\}", raw)
    if match:
        try:
            data = json.loads(match.group(0))
            if isinstance(data, dict) and all(k in data for k in CRITERIA_KEYS):
                return {key: _as_bool(data[key]) for key in CRITERIA_KEYS}
        except json.JSONDecodeError:
            pass
    out = {}
    for key in CRITERIA_KEYS:
        found = re.search(
            rf"\b{key}\b\s*[\"']?\s*[:：=]\s*(true|false|برقرار|نقض)",
            raw,
            re.I,
        )
        if found:
            token = found.group(1).lower()
            out[key] = token in ("true", "برقرار")
    if len(out) == 5:
        return out
    hits = re.findall(r"نتیجه:\s*(برقرار|نقض)", raw)
    if len(hits) >= 5:
        return {key: (val == "برقرار") for key, val in zip(CRITERIA_KEYS, hits[:5])}
    raise ValueError("Empty model response.")


def evaluate_criteria(prompt: str) -> dict:
    # JSON-mode on DeepSeek V4 often returns empty content; the prompt
    # already requires a json object, so a plain completion is more reliable.
    text = _chat(CRITERIA_SYSTEM_PROMPT, prompt, json_mode=False, max_tokens=4096)
    return parse_criteria(text)


def generate_examples(prompt: str, criteria: dict) -> list:
    failed = [key for key in CRITERIA_KEYS if not criteria.get(key)]
    if not failed:
        return []
    user_content = (
        "روش کاربر:\n"
        f"{prompt}\n\n"
        "معیارهای نقض‌شده (فقط برای همین‌ها و به همین ترتیب مثال بده):\n"
        f"{', '.join(failed)}"
    )
    text = _chat(EXAMPLES_SYSTEM_PROMPT, user_content, json_mode=True, max_tokens=4096)
    return parse_examples(text, failed)


def normalize_criteria(raw) -> dict:
    data = raw if isinstance(raw, dict) else {}
    return {key: _as_bool(data.get(key, True)) for key in CRITERIA_KEYS}


def parse_examples(text: str, failed_keys) -> list:
    raw = (text or "").strip()
    if not raw or not failed_keys:
        return []
    match = re.search(r"\{[\s\S]*\}", raw)
    blob = match.group(0) if match else raw
    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        return []
    raw_examples = data.get("examples") or []
    if isinstance(raw_examples, dict):
        raw_list = []
        for key in CRITERIA_KEYS:
            item = raw_examples.get(key)
            if isinstance(item, dict):
                item = dict(item)
                item.setdefault("rule", key)
                raw_list.append(item)
        raw_examples = raw_list
    allowed = set(failed_keys)
    examples = []
    seen = set()
    for item in raw_examples:
        if not isinstance(item, dict):
            continue
        rule = str(item.get("rule") or "").strip().upper()
        if rule not in allowed or rule in seen:
            continue
        ballots = item.get("ballots") or []
        if isinstance(ballots, str):
            ballots = [ballots]
        examples.append({
            "rule": rule,
            "title": str(item.get("title") or "").strip(),
            "ballots": [str(b).strip() for b in ballots if str(b).strip()],
            "result": str(item.get("result") or "").strip(),
            "why": str(item.get("why") or "").strip(),
        })
        seen.add(rule)
    examples.sort(key=lambda ex: CRITERIA_KEYS.index(ex["rule"]))
    return examples


class AppHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _cors(self):
        origin = self.headers.get("Origin") or "*"
        self.send_header("Access-Control-Allow-Origin", origin if origin != "null" else "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Vary", "Origin")

    def end_headers(self):
        self._cors()
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?", 1)[0].rstrip("/")
        if path == "/api/health":
            self._json(200, {"ok": True, "model": MODEL_NAME})
            return
        super().do_GET()

    def _json(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        path = self.path.split("?", 1)[0].rstrip("/")
        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self._json(400, {"error": "Body must be JSON."})
            return
        prompt = str(body.get("prompt") or "").strip()
        if path == "/api/evaluate":
            if not prompt:
                self._json(400, {"error": "prompt is required."})
                return
            try:
                criteria = evaluate_criteria(prompt)
                self._json(200, {"criteria": criteria, "prompt": prompt})
            except Exception as exc:
                self._json(502, {"error": str(exc)})
            return
        if path == "/api/examples":
            if not prompt:
                self._json(400, {"error": "prompt is required."})
                return
            try:
                criteria = normalize_criteria(body.get("criteria"))
                examples = generate_examples(prompt, criteria)
                self._json(200, {"examples": examples, "prompt": prompt})
            except Exception as exc:
                self._json(502, {"error": str(exc)})
            return
        self._json(404, {"error": "Unknown endpoint."})


def serve(host=HOST, port=PORT):
    ThreadingHTTPServer.allow_reuse_address = True
    server = ThreadingHTTPServer((host, port), AppHandler)
    print(f"Open http://127.0.0.1:{port}/index.html", flush=True)
    print("Using DeepSeek model via OrcaRouter:", MODEL_NAME, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


def main():
    prompt = input("Enter your prompt: ")
    criteria = evaluate_criteria(prompt)
    print("\n--- Criteria ---\n")
    print(json.dumps(criteria, ensure_ascii=False, indent=2))
    examples = generate_examples(prompt, criteria)
    print("\n--- Examples ---\n")
    print(json.dumps(examples, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "cli":
        main()
    else:
        serve()