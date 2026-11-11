"""Shared offline fixtures: isolated modules/storage and no external traffic."""

import importlib.util
import base64
import hashlib
import hmac
from urllib.parse import parse_qs
import json
import os
import shutil
import socket
import sys
from datetime import datetime
from pathlib import Path
from types import ModuleType, SimpleNamespace

import dotenv
import httpx
import pytest


class VectorRecords:
    """Synthetic distances and metadata; no embeddings or persistent storage."""

    def __init__(self):
        self.records = []
        self.writes = []

    def get_or_create_collection(self, **kwargs):
        return self

    def query(self, *, query_texts, n_results, where):
        def matches(metadata, condition):
            if condition is None:
                return True
            if "$and" in condition:
                return all(matches(metadata, part) for part in condition["$and"])
            return all(metadata.get(key) == value for key, value in condition.items())

        selected = [
            record for record in self.records
            if matches(record["metadata"], where)
        ][:n_results]
        return {
            "ids": [[record["message_id"] for record in selected]],
            "documents": [[record["message_text"] for record in selected]],
            "metadatas": [[record["metadata"] for record in selected]],
            "distances": [[record["distance"] for record in selected]],
        }

    def add(self, **kwargs):
        # Capture writes without inventing Chroma's duplicate/update semantics.
        self.writes.append(kwargs)


def complete_inline(coroutine):
    """Run only coroutine chains that need no event loop or asynchronous IO."""
    try:
        yielded = coroutine.send(None)
    except StopIteration as finished:
        return finished.value
    coroutine.close()
    raise AssertionError(f"Unexpected asynchronous IO in offline test: {yielded!r}")


def asgi_request(app, method, path, *, body=None, content=b"", headers=None):
    """Exercise actual FastAPI routing without Windows TestClient socketpairs.

    This intentionally supports these synchronous-completing endpoint cases only;
    it is not a replacement for lifespan, concurrency, or transport tests.
    """
    request_headers = dict(headers or {})
    if body is not None:
        content = json.dumps(body).encode("utf-8")
        request_headers["content-type"] = "application/json"
    request = httpx.Request(
        method, f"http://characterization.invalid{path}",
        content=content, headers=request_headers,
    )
    events = []
    scope = {
        "type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1", "method": method, "scheme": "http",
        "path": request.url.path, "raw_path": request.url.raw_path.split(b"?")[0],
        "query_string": request.url.query, "root_path": "",
        "headers": [(key.lower(), value) for key, value in request.headers.raw],
        "client": ("127.0.0.1", 1), "server": ("characterization.invalid", 80),
    }

    async def receive():
        return {"type": "http.request", "body": content, "more_body": False}

    async def send(event):
        events.append(event)

    complete_inline(app(scope, receive, send))
    started = next(event for event in events if event["type"] == "http.response.start")
    return httpx.Response(
        started["status"], headers=started.get("headers", []), request=request,
        content=b"".join(event.get("body", b"") for event in events
                         if event["type"] == "http.response.body"),
    )


@pytest.fixture
def router(tmp_path, monkeypatch, request):
    """Fresh modules, empty CSV state, temporary SQLite, and blocked networking."""
    source = Path(__file__).resolve().parents[1]
    workspace = tmp_path / "msg_router"
    workspace.mkdir()
    for name in ("main.py", "server.py", "vector_store.py", "dataset_store.py", "demo_data.json", "evaluate.py", "generate_data.py", "pack.py"):
        shutil.copyfile(source / name, workspace / name)
    (workspace / "static").mkdir()
    monkeypatch.chdir(workspace)
    monkeypatch.syspath_prepend(str(workspace))
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *args, **kwargs: False)
    for name in tuple(os.environ):
        if name.startswith(("GEMINI_", "GROQ_", "WHATSAPP_", "TWILIO_", "GATEWAY_", "MESSAGE_ROUTER_")):
            monkeypatch.delenv(name)

    options = getattr(request, 'param', {})
    if options == 'demo':
        options = {'demo': True, 'offline': True}
    monkeypatch.setenv('MESSAGE_ROUTER_DATA_DIR', options.get('data_dir', str(workspace / 'dataset')))
    if options.get('offline'):
        monkeypatch.setenv('MESSAGE_ROUTER_OFFLINE', 'true')
    if options.get('provider_keys'):
        monkeypatch.setenv('GEMINI_API_KEY', 'synthetic-must-not-be-used')
        monkeypatch.setenv('GROQ_API_KEY', 'synthetic-must-not-be-used')
    for name, value in options.get('settings', {}).items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv('GATEWAY_API_TOKEN', 'synthetic-gateway-token')
    network_attempts = []

    def forbid_network(*args, **kwargs):
        network_attempts.append("blocked")
        raise AssertionError("Network access is forbidden in characterization tests")

    monkeypatch.setattr(socket.socket, "connect", forbid_network)
    monkeypatch.setattr(socket.socket, "connect_ex", forbid_network)
    monkeypatch.setattr(socket, "getaddrinfo", forbid_network)
    monkeypatch.setattr(socket, "create_connection", forbid_network)
    vectors = VectorRecords()
    chroma = ModuleType("chromadb")
    chroma.PersistentClient = lambda **kwargs: vectors
    monkeypatch.setitem(sys.modules, "chromadb", chroma)

    def load(name):
        spec = importlib.util.spec_from_file_location(name, workspace / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
        return module

    server = None
    try:
        store = load('dataset_store')
        if options.get('demo'):
            store.bootstrap_demo()
        main = load("main")
        vector_store = load("vector_store")
        server = load("server")

        def seed_log(**changes):
            values = {
                "message_id": "history-1", "user_id": "u_001",
                "conversation_type": "personal", "sender_user_id": "u_002",
                "message_text": "Synthetic private update", "action": "digest",
                "message_type_pred": "personal", "digest_delivered": 0,
            }
            values.update(changes)
            with server.SessionLocal.begin() as session:
                session.add(server.GatewayLog(**values))

        def freeze_hour(hour):
            class FixedDatetime(datetime):
                @classmethod
                def now(cls, tz=None):
                    return cls(2026, 8, 1, hour, 30)

            # Do not mutate Python's shared datetime module or ORM timestamp default.
            monkeypatch.setattr(server, "datetime", SimpleNamespace(datetime=FixedDatetime))

        def prime_history():
            main.get_message_history()
            main.get_message_events()

        yield SimpleNamespace(
            main=main, server=server, vector_store=vector_store, vectors=vectors,
            store=store, load=load,
            run=complete_inline, seed_log=seed_log, freeze_hour=freeze_hour,
            prime_history=prime_history, workspace=workspace,
            http=lambda method, path, **kwargs: asgi_request(server.app, method, path, **kwargs),
        )
    finally:
        if server is not None:
            server.engine.dispose()
        assert not network_attempts, "Application attempted network access (even if it caught the error)"


@pytest.fixture
def message():
    return {
        "message_id": "incoming-1", "user_id": "u_001",
        "conversation_type": "personal", "sender_user_id": "u_002",
        "group_id": "none", "business_id": "none", "message_text": "Hello",
        "media_type": None, "media_id": None, "forwarded_count": 0,
        "created_at": "2026-08-01 12:30:00",
    }


@pytest.fixture
def history_match():
    return {
        "message_id": "history-1", "message_text": "Hello", "distance": 0.1,
        "metadata": {"user_id": "u_001", "sender_user_id": "u_002",
                     "message_replied": 1},
    }


@pytest.fixture
def client(router, monkeypatch):
    """Authenticated/signed requests for the existing endpoint smoke tests."""
    monkeypatch.setenv('WHATSAPP_APP_SECRET', 'synthetic-meta-secret')
    monkeypatch.setenv('TWILIO_AUTH_TOKEN', 'synthetic-twilio-token')

    class Client:
        def get(self, path):
            return router.http('GET', path, headers={'authorization': 'Bearer synthetic-gateway-token'})

        def post(self, path, *, json=None, content=b'', headers=None):
            request_headers = {'authorization': 'Bearer synthetic-gateway-token', **(headers or {})}
            if isinstance(content, str):
                content = content.encode()
            if path == '/api/webhook/whatsapp':
                raw = __import__('json').dumps(json).encode()
                request_headers['x-hub-signature-256'] = 'sha256=' + hmac.new(
                    b'synthetic-meta-secret', raw, hashlib.sha256).hexdigest()
            elif path == '/api/webhook/twilio-whatsapp':
                params = parse_qs(content.decode(), keep_blank_values=True)
                signed = 'http://characterization.invalid' + path + ''.join(
                    key + value for key in sorted(params) for value in sorted(set(params[key])))
                request_headers['x-twilio-signature'] = base64.b64encode(hmac.new(
                    b'synthetic-twilio-token', signed.encode(), hashlib.sha1).digest()).decode()
            return router.http('POST', path, body=json, content=content, headers=request_headers)

    return Client()
