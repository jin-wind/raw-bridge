"""aiohttp reverse proxy entry point for raw-bridge."""

from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import aiohttp
import yaml
from aiohttp import web

from .logger import TrafficLogger
from .middleware import HeaderInjector
from .normalizer import normalize_body


HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}


class ReverseProxy:
    """Receive local requests, normalize them, and forward them upstream."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.proxy_config = config.get("proxy", {})
        self.injector = HeaderInjector(config)
        self.traffic_logger = TrafficLogger(config)
        self.session: aiohttp.ClientSession | None = None

    async def start(self, app: web.Application) -> None:
        timeout = aiohttp.ClientTimeout(total=self.proxy_config.get("timeout_seconds", 300))
        self.session = aiohttp.ClientSession(timeout=timeout, auto_decompress=False)

    async def close(self, app: web.Application) -> None:
        if self.session is not None:
            await self.session.close()

    async def handle(self, request: web.Request) -> web.StreamResponse:
        if self.session is None:
            raise web.HTTPServiceUnavailable(text="Proxy session is not ready")

        started = time.perf_counter()
        body = await request.read()
        target_url = self._build_target_url(request)

        normalized_body, content_type = normalize_body(
            body,
            request.headers.get("Content-Type", ""),
        )
        outbound_headers = self._prepare_headers(request, normalized_body, content_type)
        log_context = self.traffic_logger.log_request(
            request.method,
            target_url,
            outbound_headers,
            normalized_body,
        )

        try:
            async with self.session.request(
                request.method,
                target_url,
                headers=outbound_headers,
                data=normalized_body,
                allow_redirects=False,
            ) as upstream:
                response_body = await upstream.read()
                response_headers = self._strip_hop_by_hop(dict(upstream.headers))
                latency_ms = (time.perf_counter() - started) * 1000
                self.traffic_logger.log_response(
                    log_context,
                    upstream.status,
                    response_headers,
                    response_body,
                    latency_ms,
                )
                return web.Response(
                    status=upstream.status,
                    headers=response_headers,
                    body=response_body,
                )
        except aiohttp.ClientError as exc:
            latency_ms = (time.perf_counter() - started) * 1000
            response_body = str(exc).encode("utf-8", errors="replace")
            self.traffic_logger.log_response(
                log_context,
                502,
                {"Content-Type": "text/plain; charset=utf-8"},
                response_body,
                latency_ms,
            )
            raise web.HTTPBadGateway(text=f"Upstream request failed: {exc}") from exc

    def _prepare_headers(
        self,
        request: web.Request,
        body: bytes,
        content_type: str,
    ) -> dict[str, str]:
        original = self._strip_hop_by_hop(dict(request.headers))
        original.pop("Host", None)
        original.pop("Content-Length", None)

        headers = self.injector.apply(original)
        headers["Content-Type"] = content_type
        headers["Content-Length"] = str(len(body))

        peername = request.transport.get_extra_info("peername") if request.transport else None
        if peername:
            client_ip = peername[0]
            current = headers.get("X-Forwarded-For")
            headers["X-Forwarded-For"] = f"{current}, {client_ip}" if current else client_ip
        headers["X-Forwarded-Proto"] = request.scheme
        headers["X-Forwarded-Host"] = request.host
        return headers

    def _build_target_url(self, request: web.Request) -> str:
        target_base_url = str(self.proxy_config.get("target_base_url") or "").rstrip("/")
        if target_base_url:
            return f"{target_base_url}{request.rel_url}"

        absolute_url = str(request.rel_url)
        if urlsplit(absolute_url).scheme in {"http", "https"}:
            return absolute_url

        host = request.headers.get("Host")
        if not host:
            raise web.HTTPBadRequest(text="Missing Host header and proxy.target_base_url")

        return urlunsplit(("http", host, request.rel_url.path, request.rel_url.query_string, ""))

    @staticmethod
    def _strip_hop_by_hop(headers: dict[str, str]) -> dict[str, str]:
        connection_tokens: set[str] = set()
        connection_value = next(
            (value for key, value in headers.items() if key.lower() == "connection"),
            "",
        )
        if connection_value:
            connection_tokens = {
                token.strip().lower()
                for token in connection_value.split(",")
                if token.strip()
            }

        blocked = HOP_BY_HOP_HEADERS | connection_tokens
        return {key: value for key, value in headers.items() if key.lower() not in blocked}


def load_config(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle) or {}
    if not isinstance(loaded, dict):
        raise ValueError("Config root must be a mapping")
    return loaded


def create_app(config: dict[str, Any]) -> web.Application:
    proxy = ReverseProxy(config)
    app = web.Application(client_max_size=config.get("proxy", {}).get("client_max_size", 1024**3))
    app.on_startup.append(proxy.start)
    app.on_cleanup.append(proxy.close)
    app.router.add_route("*", "/{path_info:.*}", proxy.handle)
    return app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the raw-bridge local reverse proxy.")
    parser.add_argument("--config", default="config.yaml", help="Path to YAML config file.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    proxy_cfg = config.get("proxy", {})
    web.run_app(
        create_app(config),
        host=proxy_cfg.get("listen_host", "127.0.0.1"),
        port=int(proxy_cfg.get("listen_port", 8080)),
    )


if __name__ == "__main__":
    main()
