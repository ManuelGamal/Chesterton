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


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("content-length") or 0)
        try:
            payload = json.loads(self.rfile.read(length) or b"null")
        except json.JSONDecodeError:
            payload = None
        result = asyncio.run(answer(payload, stories_dir=STORIES, client=NemotronClient(),
                                    counter=UpstashCounter.from_env()))
        body = json.dumps(result.body).encode("utf-8")
        self.send_response(result.status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
