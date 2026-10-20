#!/usr/bin/env python3
"""A stand-in Neptune Apex for testing shortcuts without touching the tank.

Serves the slice of the AOS 5 local API that the shortcuts use, keeps feed
state in memory, and logs every request along with anything that differs from
what the real dashboard sends (JSON types, content type, missing session).

    python3 tools/mock_apex.py    # http://127.0.0.1:8737, login admin / mock-password

Login hands out two equally valid session ids, one in the JSON body and one
via Set-Cookie, so the log shows whether a request authenticated with the
Cookie header built from the body, with Shortcuts' own cookie jar, or both.
"""
from __future__ import annotations

import argparse
import json
import re
import secrets
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

FEED_SECONDS = 300  # every mock feed cycle lasts 5 minutes


class MockApex:
    def __init__(self, username: str, password: str):
        self.username = username
        self.password = password
        self.sessions: dict[str, str] = {}  # session id -> how the client received it
        self.feed_name = 0
        self.feed_ends = 0.0

    def login(self) -> tuple[str, str]:
        body_sid, jar_sid = (secrets.token_hex(12) for _ in range(2))  # 24 characters, like the Apex's
        self.sessions[body_sid] = "header built from login body"
        self.sessions[jar_sid] = "Shortcuts cookie jar"
        return body_sid, jar_sid

    def set_feed(self, name: int) -> None:
        self.feed_name = name
        self.feed_ends = time.time() + FEED_SECONDS if name else 0.0

    def feed(self) -> dict:
        remaining = max(0, round(self.feed_ends - time.time()))
        if remaining == 0:
            self.feed_name = 0
        return {"name": self.feed_name, "active": remaining}


def type_problems(body: dict, expected: dict[str, type]) -> list[str]:
    problems = []
    for key, kind in expected.items():
        value = body.get(key)
        # bool is a subclass of int, so check it explicitly: the Apex wants 1, not true
        if not isinstance(value, kind) or (kind is int and isinstance(value, bool)):
            problems.append(f"{key} is {value!r} ({type(value).__name__}), dashboard sends {kind.__name__}")
    return problems


class Handler(BaseHTTPRequestHandler):
    apex: MockApex
    server_version = "AquaController 5.0"  # what the real Apex reports
    sys_version = ""

    def do_GET(self) -> None:
        self.handle_api()

    do_POST = do_PUT = do_GET

    def handle_api(self) -> None:
        self.notes: list[str] = []
        self.cookie_to_set: str | None = None
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        path = self.path.split("?")[0]
        feed = re.fullmatch(r"/rest/status/feed/(\d+)", path)

        if self.command == "POST" and path == "/rest/login":
            status, payload = self.login(raw)
        elif self.command == "PUT" and feed:
            status, payload = self.put_feed(int(feed.group(1)), raw)
        elif self.command == "GET" and path == "/cgi-bin/status.json":
            istat = {"hostname": "MockApex", "software": "5.16L_AC26", "feed": self.apex.feed()}
            status, payload = 200, {"istat": istat}
        else:
            status, payload = 404, None

        self.send(status, payload)
        self.log_request_summary(status, raw)

    def login(self, raw: bytes) -> tuple[int, dict | None]:
        body = self.json_body(raw)
        if body is None:
            return 400, None
        self.notes += type_problems(body, {"login": str, "password": str, "remember_me": bool})
        if (body.get("login"), body.get("password")) != (self.apex.username, self.apex.password):
            self.notes.append("wrong username or password")
            return 401, None
        body_sid, jar_sid = self.apex.login()
        self.cookie_to_set = f"connect.sid={jar_sid}; Path=/; HttpOnly"
        return 200, {"connect.sid": body_sid}

    def put_feed(self, feed_id: int, raw: bytes) -> tuple[int, dict | None]:
        if not self.has_session():
            return 401, None
        body = self.json_body(raw)
        if body is None:
            return 400, None
        problems = type_problems(body, {"name": int, "active": int})
        if body.get("name") != feed_id:
            problems.append(f"body name {body.get('name')!r} doesn't match URL id {feed_id}")
        if not 0 <= feed_id <= 4:
            problems.append(f"feed id {feed_id} isn't 0 (cancel) or 1-4 (A-D)")
        if problems:
            self.notes += problems
            return 400, None
        self.apex.set_feed(feed_id)
        return 200, {**body, "errorCode": 0, "errorMessage": ""}  # the Apex echoes the request

    def has_session(self) -> bool:
        sids = re.findall(r"connect\.sid=([^;\s]*)", self.headers.get("Cookie", ""))
        how = [self.apex.sessions.get(sid, f"unknown session {sid!r}") for sid in sids]
        self.notes.append("session via: " + (", ".join(how) or "nothing (no connect.sid cookie)"))
        return any(sid in self.apex.sessions for sid in sids)

    def json_body(self, raw: bytes) -> dict | None:
        content_type = self.headers.get("Content-Type", "")
        if not content_type.startswith("application/json"):
            self.notes.append(f"Content-Type is {content_type!r}, dashboard sends application/json")
        try:
            body = json.loads(raw)
        except ValueError:
            self.notes.append(f"body isn't JSON: {raw[:200]!r}")
            return None
        if not isinstance(body, dict):
            self.notes.append(f"body is a JSON {type(body).__name__}, expected an object")
            return None
        return body

    def send(self, status: int, payload: dict | None) -> None:
        if payload is None:  # the Apex's own error page
            title = f"{status} {self.responses[status][0]}"
            data, content_type = f"<HTML><HEAD><TITLE>{title}</TITLE></HEAD><BODY>{title}</BODY></HTML>".encode(), "text/html"
        else:
            data, content_type = json.dumps(payload).encode(), "application/json"
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        if self.cookie_to_set:
            self.send_header("Set-Cookie", self.cookie_to_set)
        self.end_headers()
        self.wfile.write(data)

    def log_request_summary(self, status: int, raw: bytes) -> None:
        body = raw.decode(errors="replace")
        body = re.sub(r'("password"\s*:\s*)"[^"]*"', r'\1"<redacted>"', body)
        lines = [
            f"{time.strftime('%H:%M:%S')}  {self.command} {self.path} -> {status}",
            f"    Content-Type: {self.headers.get('Content-Type')}  User-Agent: {self.headers.get('User-Agent')}",
        ]
        if body:
            lines.append(f"    body: {body}")
        lines += [f"    * {note}" for note in self.notes]
        print("\n".join(lines), flush=True)

    def log_message(self, format: str, *args) -> None:
        pass  # replaced by log_request_summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Fake Neptune Apex for testing shortcuts.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8737)
    parser.add_argument("--username", default="admin")
    parser.add_argument("--password", default="mock-password")
    args = parser.parse_args()

    Handler.apex = MockApex(args.username, args.password)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Mock Apex on http://{args.host}:{args.port}  (login {args.username} / {args.password})", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
