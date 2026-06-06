"""aiohttp reverse proxy entry point for raw-bridge.

Uses curl_cffi with browser TLS impersonation for clean transparent forwarding.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import Any

import yaml
from aiohttp import web
from curl_cffi import requests as cffi_requests

from .logger import TrafficLogger
from .middleware import HeaderInjector
from .normalizer import normalize_body


# ── Headers to always strip before forwarding ────────────────────────────────
STRIPPED_PREFIXES = ("x-forwarded-",)
STRIPPED_EXACT = {"host", "x-forwarded-for", "x-forwarded-proto", "x-forwarded-host"}


class ReverseProxy:
    """Receive local requests, normalize them, and forward them upstream
    using curl_cffi with Chrome TLS fingerprint impersonation."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.proxy_config = config.get("proxy", {})
        self.injector = HeaderInjector(config)
        self.traffic_logger = TrafficLogger(config)

    async def handle(self, request: web.Request) -> web.StreamResponse:
        started = time.perf_counter()
        body = await request.read()
        target_url = self._build_target_url(request)

        normalized_body, content_type = normalize_body(
            body, request.headers.get("Content-Type", "")
        )
        outbound_headers = self._prepare_headers(request, normalized_body, content_type)

        log_context = self.traffic_logger.log_request(
            request.method, target_url, outbound_headers, normalized_body
        )

        try:
            resp = cffi_requests.request(
                method=request.method,
                url=target_url,
                headers=outbound_headers,
                data=normalized_body if normalized_body else None,
                allow_redirects=False,
                impersonate="chrome120",
                timeout=self.proxy_config.get("timeout_seconds", 300),
            )

            response_body = resp.content
            response_headers = {
                k: v for k, v in resp.headers.items()
                if k.lower() not in {"transfer-encoding", "connection"}
            }
            latency_ms = (time.perf_counter() - started) * 1000

            self.traffic_logger.log_response(
                log_context, resp.status_code, response_headers, response_body, latency_ms
            )
            return web.Response(
                status=resp.status_code, headers=response_headers, body=response_body
            )

        except Exception as exc:
            latency_ms = (time.perf_counter() - started) * 1000
            err_body = str(exc).encode("utf-8", errors="replace")
            self.traffic_logger.log_response(
                log_context, 502, {"Content-Type": "text/plain"}, err_body, latency_ms
            )
            raise web.HTTPBadGateway(text=f"Upstream request failed: {exc}") from exc

    def _prepare_headers(
        self, request: web.Request, body: bytes, content_type: str
    ) -> dict[str, str]:
        """Build clean outbound headers — no X-Forwarded-*, no Host."""
        original = dict(request.headers)

        # Strip everything that leaks proxy identity
        filtered = {}
        for k, v in original.items():
            kl = k.lower()
            if kl in STRIPPED_EXACT:
                continue
            if any(kl.startswith(p) for p in STRIPPED_PREFIXES):
                continue
            filtered[k] = v

        # Apply injection rules (User-Agent, originator, Authorization, etc.)
        headers = self.injector.apply(filtered)
        headers["Content-Type"] = content_type
        headers["Content-Length"] = str(len(body))
        return headers

    def _build_target_url(self, request: web.Request) -> str:
        target_base_url = str(self.proxy_config.get("target_base_url") or "").rstrip("/")
        if target_base_url:
            return f"{target_base_url}{request.rel_url}"
        return str(request.rel_url)


def load_config(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle) or {}
    if not isinstance(loaded, dict):
        raise ValueError("Config root must be a mapping")
    return loaded


def create_app(config: dict[str, Any]) -> web.Application:
    proxy = ReverseProxy(config)
    app = web.Application(client_max_size=config.get("proxy", {}).get("client_max_size", 1024**3))
    app.router.add_route("*", "/{path_info:.*}", proxy.handle)
    return app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the raw-bridge local reverse proxy.")
    parser.add_argument("--config", default="config.yaml", help="Path to YAML config file.")
    parser.add_argument("--port", type=int, default=None, help="Override listen_port.")
    parser.add_argument("--target", default=None, help="Override target_base_url.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    if args.port:
        config.setdefault("proxy", {})["listen_port"] = args.port
    if args.target:
        config.setdefault("proxy", {})["target_base_url"] = args.target

    proxy_cfg = config.get("proxy", {})
    web.run_app(
        create_app(config),
        host=proxy_cfg.get("listen_host", "127.0.0.1"),
        port=int(proxy_cfg.get("listen_port", 8080)),
    )


if __name__ == "__main__":
    main()
