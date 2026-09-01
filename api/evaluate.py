from _llm import evaluate_criteria
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
            criteria = evaluate_criteria(prompt)
            self.send_json(200, {"criteria": criteria, "prompt": prompt})
        except Exception as exc:
            self.send_json(502, {"error": str(exc)})
