from __future__ import annotations

import json

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer, unused_port

from proxy.server import create_app


async def test_proxy_injects_headers_and_normalizes_form_body(aiohttp_client) -> None:
    captured = {}

    async def upstream_handler(request: web.Request) -> web.Response:
        captured["headers"] = dict(request.headers)
        captured["body"] = await request.json()
        return web.json_response({"ok": True, "body": captured["body"]}, status=201)

    upstream_app = web.Application()
    upstream_app.router.add_route("*", "/{path_info:.*}", upstream_handler)

    upstream_server = TestServer(upstream_app, port=unused_port())
    upstream_client = TestClient(upstream_server)
    await upstream_client.start_server()

    try:
        config = {
            "proxy": {
                "target_base_url": str(upstream_client.make_url("")).rstrip("/"),
            },
            "headers": {
                "inject": {
                    "User-Agent": "raw-bridge-test/1.0",
                    "X-Forwarded-By": "local-middleware",
                },
                "override_original": True,
                "passthrough_whitelist": [],
            },
            "logging": {
                "level": "CRITICAL",
                "log_request_body": True,
                "log_response_body": True,
            },
        }
        proxy_client = await aiohttp_client(create_app(config))

        response = await proxy_client.post(
            "/echo?source=test",
            data="name=raw-bridge&mode=test",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": "caller/0.1",
            },
        )

        assert response.status == 201
        assert await response.json() == {
            "ok": True,
            "body": {"name": "raw-bridge", "mode": "test"},
        }
        assert captured["headers"]["User-Agent"] == "raw-bridge-test/1.0"
        assert captured["headers"]["X-Forwarded-By"] == "local-middleware"
        assert captured["headers"]["Content-Type"] == "application/json"
        assert captured["body"] == {"name": "raw-bridge", "mode": "test"}
    finally:
        await upstream_client.close()


def test_json_normalization_keeps_valid_payload() -> None:
    from proxy.normalizer import normalize_body

    body, content_type = normalize_body(json.dumps({"a": 1}).encode(), "application/json")

    assert content_type == "application/json"
    assert json.loads(body) == {"a": 1}
