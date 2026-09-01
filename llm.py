import json
import os
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from api._llm import (
    MODEL_NAME,
    evaluate_criteria,
    generate_examples,
    get_api_key,
    normalize_criteria,
    save_env_key,
    _clean_env_value,
    _is_real_key,
)

HOST = "0.0.0.0"
PORT = 8765
ROOT = Path(__file__).resolve().parent


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
    try:
        return get_api_key()
    except RuntimeError:
        key = prompt_for_api_key()
        os.environ["ORCAROUTER_API_KEY"] = key
        return key


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
    require_api_key()
    ThreadingHTTPServer.allow_reuse_address = True
    server = ThreadingHTTPServer((host, port), AppHandler)
    print(f"Open http://127.0.0.1:{port}/index.html", flush=True)
    print("Using DeepSeek model via OrcaRouter:", MODEL_NAME, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


def main():
    require_api_key()
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
