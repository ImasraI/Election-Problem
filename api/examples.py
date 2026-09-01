from _llm import generate_examples, normalize_criteria
from _util import JsonHandler


class handler(JsonHandler):
    def do_POST(self):
        try:
            body = self.read_json()
        except Exception:
            self.send_json(400, {"error": "Body must be JSON."})
            return
        prompt = str(body.get("prompt") or "").strip()
        if not prompt:
            self.send_json(400, {"error": "prompt is required."})
            return
        try:
            criteria = normalize_criteria(body.get("criteria"))
            examples = generate_examples(prompt, criteria)
            self.send_json(200, {"examples": examples, "prompt": prompt})
        except Exception as exc:
            self.send_json(502, {"error": str(exc)})
