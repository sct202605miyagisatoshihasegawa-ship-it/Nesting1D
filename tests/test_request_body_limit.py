# Nesting1D - HTTP本文サイズ制限テスト
# 役割: 設定解析、境界値、ASGI受信、および400・413応答を検証する。
# 更新日: 2026-08-10

import asyncio
import json

import pytest
from fastapi.testclient import TestClient
from starlette.responses import JSONResponse

import app.main as main_module
from app.request_limits import (
    DEFAULT_MAX_REQUEST_BODY_BYTES,
    RequestBodyLimitMiddleware,
    parse_max_request_body_bytes,
)
from tests.test_checkpoint5 import direct_export_request
from tests.test_production_security import SECURITY_HEADERS
from tests.test_web_calculation import normal


def assert_security_headers(response) -> None:
    for name, value in SECURITY_HEADERS.items():
        assert response.headers[name] == value


@pytest.mark.parametrize("configured", [None, ""])
def test_default_request_body_limit(monkeypatch, configured) -> None:
    if configured is None:
        monkeypatch.delenv("MAX_REQUEST_BODY_BYTES", raising=False)
    else:
        monkeypatch.setenv("MAX_REQUEST_BODY_BYTES", configured)

    assert parse_max_request_body_bytes() == DEFAULT_MAX_REQUEST_BODY_BYTES


@pytest.mark.parametrize(
    ("configured", "expected"),
    [("1", 1), ("262144", 262_144), ("  512  ", 512)],
)
def test_valid_request_body_limit(configured: str, expected: int) -> None:
    assert parse_max_request_body_bytes(configured) == expected


@pytest.mark.parametrize("configured", ["0", "-1", "12.5", "invalid", "+1", "１２"])
def test_invalid_request_body_limit_raises(configured: str) -> None:
    with pytest.raises(ValueError, match="MAX_REQUEST_BODY_BYTES"):
        parse_max_request_body_bytes(configured)


def test_existing_gets_forms_and_exports_remain_available() -> None:
    client = TestClient(main_module.app)

    for path in ("/", "/health", "/robots.txt", "/static/css/style.css"):
        assert client.get(path).status_code == 200
    assert client.post("/", data=normal()).status_code == 200

    request = direct_export_request()
    json_response = client.post("/api/export/json", json=request)
    html_response = client.post("/api/export/html", json=request)
    assert json_response.status_code == html_response.status_code == 200
    assert json_response.headers["content-disposition"].endswith('.json"')
    assert json_response.headers["cache-control"] == "no-store"
    assert html_response.headers["content-disposition"].endswith('.html"')
    assert html_response.headers["cache-control"] == "no-store"
    assert html_response.headers["pragma"] == "no-cache"


@pytest.mark.parametrize(
    ("path", "content_type"),
    [
        ("/", "application/x-www-form-urlencoded"),
        ("/api/export/json", "application/json"),
        ("/api/export/html", "application/json"),
    ],
)
def test_protected_post_routes_reject_oversized_bodies(
    path: str,
    content_type: str,
) -> None:
    response = TestClient(main_module.app).post(
        path,
        content=b"x" * (DEFAULT_MAX_REQUEST_BODY_BYTES + 1),
        headers={"Content-Type": content_type},
    )

    assert_limit_error(response, 413, "Request body too large")


@pytest.mark.parametrize("content_length", ["-1", "not-a-number", "1, 1"])
def test_invalid_content_length_returns_safe_400(content_length: str) -> None:
    response = TestClient(main_module.app).post(
        "/api/export/json",
        content=b"{}",
        headers={
            "Content-Type": "application/json",
            "Content-Length": content_length,
        },
    )

    assert_limit_error(response, 400, "Invalid Content-Length")
    assert "Traceback" not in response.text


def test_declared_small_body_is_rejected_when_actual_body_exceeds_limit() -> None:
    response = TestClient(main_module.app).post(
        "/api/export/json",
        content=b"x" * (DEFAULT_MAX_REQUEST_BODY_BYTES + 1),
        headers={
            "Content-Type": "application/json",
            "Content-Length": "1",
        },
    )

    assert_limit_error(response, 413, "Request body too large")


def assert_limit_error(response, status_code: int, detail: str) -> None:
    assert response.status_code == status_code
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {"detail": detail}
    assert response.headers["cache-control"] == "no-store"
    assert_security_headers(response)


def run_asgi_request(
    body_chunks: list[bytes],
    *,
    max_bytes: int,
    content_length_headers: list[bytes] | None = None,
    downstream=None,
    messages=None,
):
    async def default_downstream(scope, receive, send) -> None:
        received = bytearray()
        while True:
            message = await receive()
            if message["type"] != "http.request":
                break
            received.extend(message.get("body", b""))
            if not message.get("more_body", False):
                break
        await JSONResponse({"received": len(received)})(scope, receive, send)

    downstream = downstream or default_downstream

    headers = [
        (b"content-length", value)
        for value in (content_length_headers or [])
    ]
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "root_path": "",
        "headers": headers,
        "client": ("test", 123),
        "server": ("test", 80),
    }
    if messages is None:
        messages = [
            {
                "type": "http.request",
                "body": chunk,
                "more_body": index < len(body_chunks) - 1,
            }
            for index, chunk in enumerate(body_chunks)
        ]
    sent = []

    async def receive():
        if messages:
            return messages.pop(0)
        return {"type": "http.disconnect"}

    async def send(message) -> None:
        sent.append(message)

    asyncio.run(RequestBodyLimitMiddleware(downstream, max_bytes)(scope, receive, send))
    if not sent:
        return None, {}, None
    start = next(message for message in sent if message["type"] == "http.response.start")
    body = b"".join(
        message.get("body", b"")
        for message in sent
        if message["type"] == "http.response.body"
    )
    return start["status"], dict(start["headers"]), json.loads(body)


def test_exact_limit_without_content_length_reaches_downstream() -> None:
    status_code, _, body = run_asgi_request([b"12", b"345"], max_bytes=5)

    assert status_code == 200
    assert body == {"received": 5}


def test_chunked_body_one_byte_over_limit_is_rejected() -> None:
    status_code, headers, body = run_asgi_request(
        [b"12", b"345", b"6"],
        max_bytes=5,
    )

    assert status_code == 413
    assert body == {"detail": "Request body too large"}
    assert dict(headers)[b"cache-control"] == b"no-store"


def test_declared_small_chunked_body_is_still_measured() -> None:
    status_code, _, body = run_asgi_request(
        [b"123", b"456"],
        max_bytes=5,
        content_length_headers=[b"3"],
    )

    assert status_code == 413
    assert body == {"detail": "Request body too large"}


@pytest.mark.parametrize("content_length_headers", [None, [b"1"]])
def test_oversized_body_is_rejected_even_when_downstream_never_receives(
    content_length_headers,
) -> None:
    called = False

    async def downstream(scope, receive, send) -> None:
        nonlocal called
        called = True
        await JSONResponse({"unexpected": True})(scope, receive, send)

    status_code, _, body = run_asgi_request(
        [b"123", b"456"],
        max_bytes=5,
        content_length_headers=content_length_headers,
        downstream=downstream,
    )

    assert status_code == 413
    assert body == {"detail": "Request body too large"}
    assert not called


def test_single_oversized_chunk_is_not_saved_or_replayed_downstream() -> None:
    called = False
    replayed_messages = []

    async def downstream(scope, receive, send) -> None:
        nonlocal called
        called = True
        replayed_messages.append(await receive())

    status_code, _, body = run_asgi_request(
        [b"123456"],
        max_bytes=5,
        downstream=downstream,
    )

    assert status_code == 413
    assert body == {"detail": "Request body too large"}
    assert not called
    assert replayed_messages == []


def test_saved_request_messages_are_replayed_in_order_without_copying() -> None:
    original_messages = [
        {"type": "http.request", "body": b"12", "more_body": True},
        {"type": "http.request", "body": b"345", "more_body": False},
    ]
    replayed_messages = []

    async def downstream(scope, receive, send) -> None:
        replayed_messages.append(await receive())
        replayed_messages.append(await receive())
        await JSONResponse({"received": 5})(scope, receive, send)

    status_code, _, body = run_asgi_request(
        [],
        max_bytes=5,
        downstream=downstream,
        messages=list(original_messages),
    )

    assert status_code == 200
    assert body == {"received": 5}
    assert replayed_messages == original_messages
    assert all(
        replayed is original
        for replayed, original in zip(replayed_messages, original_messages)
    )


def test_size_check_finishes_before_downstream_can_start_response() -> None:
    events = []

    async def downstream(scope, receive, send) -> None:
        events.append("downstream_called")
        await JSONResponse({"received": True})(scope, receive, send)

    class TrackedMessages(list):
        def pop(self, index=0):
            message = super().pop(index)
            events.append(("request_received", message.get("body", b"")))
            return message

    messages = TrackedMessages(
        [
            {"type": "http.request", "body": b"12", "more_body": True},
            {"type": "http.request", "body": b"345", "more_body": False},
        ]
    )
    status_code, _, _ = run_asgi_request(
        [], max_bytes=5, downstream=downstream, messages=messages
    )

    assert status_code == 200
    assert events == [
        ("request_received", b"12"),
        ("request_received", b"345"),
        "downstream_called",
    ]


def test_disconnect_aborts_without_calling_downstream_or_sending_response() -> None:
    called = False

    async def downstream(scope, receive, send) -> None:
        nonlocal called
        called = True

    status_code, headers, body = run_asgi_request(
        [],
        max_bytes=5,
        downstream=downstream,
        messages=[
            {"type": "http.request", "body": b"12", "more_body": True},
            {"type": "http.disconnect"},
        ],
    )

    assert (status_code, headers, body) == (None, {}, None)
    assert not called


def test_content_length_over_limit_is_rejected_before_receive() -> None:
    status_code, _, body = run_asgi_request(
        [],
        max_bytes=5,
        content_length_headers=[b"6"],
    )

    assert status_code == 413
    assert body == {"detail": "Request body too large"}


def test_duplicate_content_length_is_rejected() -> None:
    status_code, _, body = run_asgi_request(
        [b"123"],
        max_bytes=5,
        content_length_headers=[b"3", b"3"],
    )

    assert status_code == 400
    assert body == {"detail": "Invalid Content-Length"}


def test_non_http_scope_passes_through_unchanged() -> None:
    called = False

    async def downstream(scope, receive, send) -> None:
        nonlocal called
        called = scope["type"] == "websocket"

    async def run() -> None:
        async def receive():
            return {"type": "websocket.disconnect", "code": 1000}

        async def send(message) -> None:
            raise AssertionError("send should not be called")

        middleware = RequestBodyLimitMiddleware(downstream, 5)
        await middleware({"type": "websocket"}, receive, send)

    asyncio.run(run())
    assert called



def test_default_limit_accepts_exact_65536_bytes():
    assert DEFAULT_MAX_REQUEST_BODY_BYTES == 65_536
    status_code, _, body = run_asgi_request(
        [b"x" * DEFAULT_MAX_REQUEST_BODY_BYTES],
        max_bytes=DEFAULT_MAX_REQUEST_BODY_BYTES,
    )
    assert status_code == 200
    assert body == {"received": DEFAULT_MAX_REQUEST_BODY_BYTES}


def test_default_limit_rejects_65537_bytes_before_downstream():
    called = False

    async def downstream(scope, receive, send) -> None:
        nonlocal called
        called = True

    status_code, _, body = run_asgi_request(
        [b"x" * (DEFAULT_MAX_REQUEST_BODY_BYTES + 1)],
        max_bytes=DEFAULT_MAX_REQUEST_BODY_BYTES,
        downstream=downstream,
    )
    assert status_code == 413
    assert body == {"detail": "Request body too large"}
    assert not called
