"""Vercel adapter for the demo's live call. All logic is in chesterton.demo.why."""

import asyncio
import json
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from chesterton.demo.why import UpstashCounter, answer  # noqa: E402
from chesterton.llm.client import NemotronClient  # noqa: E402

STORIES = ROOT / "web" / "public" / "stories"
#: Vercel's own request-body cap is much larger; this keeps the demo's one
#: payload shape (two short ids) from being used to smuggle anything bigger.
MAX_BODY_BYTES = 4096


def _respond(conn: BaseHTTPRequestHandler, status: int, body: dict, *, headers: dict | None = None) -> None:
    payload = json.dumps(body).encode("utf-8")
    conn.send_response(status)
    conn.send_header("content-type", "application/json")
    conn.send_header("content-length", str(len(payload)))
    for name, value in (headers or {}).items():
        conn.send_header(name, value)
    conn.end_headers()
    conn.wfile.write(payload)


def _method_not_allowed(conn: BaseHTTPRequestHandler) -> None:
    _respond(conn, 405, {"error": "method_not_allowed", "message": "use POST", "recorded": None},
             headers={"Allow": "POST"})


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        _method_not_allowed(self)

    def do_PUT(self):
        _method_not_allowed(self)

    def do_DELETE(self):
        _method_not_allowed(self)

    def do_PATCH(self):
        _method_not_allowed(self)

    def do_POST(self):
        try:
            length = int(self.headers.get("content-length") or 0)
            if length < 0:
                length = 0
        except ValueError:
            length = 0
        if length > MAX_BODY_BYTES:
            _respond(self, 413, {"error": "too_large", "message": "request body too large", "recorded": None})
            return
        try:
            payload = json.loads(self.rfile.read(length) or b"null")
        except json.JSONDecodeError:
            payload = None
        try:
            result = asyncio.run(answer(payload, stories_dir=STORIES, client=NemotronClient(),
                                        counter=UpstashCounter.from_env()))
        except Exception:
            _respond(self, 500, {"error": "internal", "message": "the live call failed", "recorded": None})
            return
        _respond(self, result.status, result.body)
