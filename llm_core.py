import json
import os
import re
import sys
from pathlib import Path

import requests

OPENAI_API_BASE = "https://api.orcarouter.ai/v1"
OPENAI_CHAT_URL = f"{OPENAI_API_BASE}/chat/completions"
MODEL_NAME = "deepseek/deepseek-v4-flash-free"
CRITERIA_KEYS = ["AAW", "CWC", "UNAN", "MONO", "IIA"]
PLACEHOLDER_KEYS = {"", "your_orcarouter_api_key_here", "changeme"}

ROOT = Path(__file__).resolve().parent
ENV_PATH = ROOT / ".env"

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


def _clean_env_value(value: str) -> str:
    value = (value or "").strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    return value.strip()


def _is_real_key(key: str) -> bool:
    return bool(key) and key.lower() not in PLACEHOLDER_KEYS


def read_env_file_key(path=None) -> str:
    path = path or ENV_PATH
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


def get_api_key() -> str:
    key = _clean_env_value(os.environ.get("ORCAROUTER_API_KEY", ""))
    if _is_real_key(key):
        return key
    key = read_env_file_key(ENV_PATH)
    if _is_real_key(key):
        os.environ["ORCAROUTER_API_KEY"] = key
        return key
    raise RuntimeError(
        "ORCAROUTER_API_KEY is not set. Add it in Vercel Environment Variables "
        "or a local .env file."
    )


def _request_timeout() -> int:
    if os.environ.get("VERCEL"):
        return 50
    return 300


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
    for key in ("reasoning_content", "reasoning"):
        extra = _flatten_content(msg.get(key))
        if extra:
            return extra
    return ""


def _chat(system_prompt: str, user_content: str, *, json_mode: bool, max_tokens: int) -> str:
    api_key = get_api_key()
    headers = {
        "Authorization": f"Bearer {api_key}",
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
        "thinking": {"type": "disabled"},
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    timeout = _request_timeout()
    last_text = ""
    attempts = 2
    for attempt in range(attempts):
        body = dict(payload)
        if attempt == 1:
            body.pop("response_format", None)
            body.pop("thinking", None)
        try:
            response = requests.post(OPENAI_CHAT_URL, headers=headers, json=body, timeout=timeout)
            if response.status_code in (400, 422) and (
                "thinking" in body or "max_completion_tokens" in body or "response_format" in body
            ):
                for drop in ("thinking", "max_completion_tokens", "response_format"):
                    body.pop(drop, None)
                response = requests.post(OPENAI_CHAT_URL, headers=headers, json=body, timeout=timeout)
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
