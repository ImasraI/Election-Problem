import os
import sys

import uvicorn

from app import app
from llm_core import (
    MODEL_NAME,
    evaluate_criteria,
    generate_examples,
    get_api_key,
    save_env_key,
    _clean_env_value,
    _is_real_key,
)

HOST = "0.0.0.0"
PORT = 8765


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


def serve(host=HOST, port=PORT):
    require_api_key()
    print(f"Open http://127.0.0.1:{port}/index.html", flush=True)
    print("Admin login: username admin  (password from ADMIN_PASSWORD, default admin)", flush=True)
    print("Using DeepSeek model via OrcaRouter:", MODEL_NAME, flush=True)
    uvicorn.run(app, host=host, port=port, log_level="info")


def main():
    require_api_key()
    import json
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
