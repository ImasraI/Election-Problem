from _llm import MODEL_NAME
from _util import JsonHandler


class handler(JsonHandler):
    def do_GET(self):
        self.send_json(200, {"ok": True, "model": MODEL_NAME})
