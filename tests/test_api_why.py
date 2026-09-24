"""Tests for the Vercel adapter in api/why.py: the method and body-size guards.

These drive `handler` over a real loopback HTTP connection so
BaseHTTPRequestHandler's own response-writing machinery runs unmocked. Both
guards return before `chesterton.demo.why.answer` is ever called, so no
story data, model client or counter is touched -- no live call is possible
from these tests.
"""

from __future__ import annotations

import http.client
import importlib.util
import json
import sys
import threading
from http.server import HTTPServer
from pathlib import Path

import pytest

API_WHY = Path(__file__).resolve().parents[1] / "api" / "why.py"
_spec = importlib.util.spec_from_file_location("api_why", API_WHY)
api_why = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("api_why", api_why)
_spec.loader.exec_module(api_why)


@pytest.fixture
def server():
    httpd = HTTPServer(("127.0.0.1", 0), api_why.handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield httpd
    finally:
        httpd.shutdown()
        thread.join()


def _connection(httpd) -> http.client.HTTPConnection:
    host, port = httpd.server_address
    return http.client.HTTPConnection(host, port, timeout=5)


def test_a_body_over_4096_bytes_is_rejected_with_413_before_any_live_call(server):
    conn = _connection(server)
    body = b"x" * 4097
    conn.request("POST", "/", body=body, headers={"Content-Length": str(len(body))})
    response = conn.getresponse()
    payload = json.loads(response.read())
    conn.close()

    assert response.status == 413
    assert payload == {"error": "too_large", "message": "request body too large", "recorded": None}


def test_a_body_at_the_4096_byte_limit_is_not_rejected_for_size(server):
    conn = _connection(server)
    body = b"x" * 4096  # invalid JSON, but under the size cap: rejected for shape, not size
    conn.request("POST", "/", body=body, headers={"Content-Length": str(len(body))})
    response = conn.getresponse()
    payload = json.loads(response.read())
    conn.close()

    assert response.status != 413
    assert payload["error"] != "too_large"


@pytest.mark.parametrize("method", ["GET", "PUT", "DELETE", "PATCH"])
def test_other_methods_are_rejected_with_405_and_an_allow_header(server, method):
    conn = _connection(server)
    conn.request(method, "/")
    response = conn.getresponse()
    payload = json.loads(response.read())
    conn.close()

    assert response.status == 405
    assert response.getheader("Allow") == "POST"
    assert payload["error"] == "method_not_allowed"
    assert payload["recorded"] is None
