"""Structured request and response traffic logging."""

import json
import logging
import os
import time
from typing import Any


class TrafficLogger:
    """Log each proxied request as one structured JSON record."""

    def __init__(self, config: dict[str, Any]) -> None:
        log_cfg = config.get("logging", {})
        self.log_request_body: bool = log_cfg.get("log_request_body", True)
        self.log_response_body: bool = log_cfg.get("log_response_body", True)

        self._logger = logging.getLogger("raw-bridge")
        self._logger.setLevel(getattr(logging, log_cfg.get("level", "INFO").upper()))
        self._logger.propagate = False
        self._logger.handlers.clear()

        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)-7s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        console = logging.StreamHandler()
        console.setFormatter(formatter)
        self._logger.addHandler(console)

        log_file = log_cfg.get("log_file")
        if log_file:
            os.makedirs(os.path.dirname(log_file) or ".", exist_ok=True)
            file_handler = logging.FileHandler(log_file, encoding="utf-8")
            file_handler.setFormatter(formatter)
            self._logger.addHandler(file_handler)

    def log_request(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
    ) -> dict[str, Any]:
        """記錄並回傳本次請求的流量上下文（供後續關聯 Response）。"""
        context: dict[str, Any] = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "method": method,
            "url": url,
            "request_headers": dict(headers),
        }
        if self.log_request_body and body:
            try:
                context["request_body"] = json.loads(body)
            except (json.JSONDecodeError, UnicodeDecodeError):
                context["request_body"] = body.decode("utf-8", errors="replace")
        return context

    def log_response(
        self,
        context: dict[str, Any],
        status: int,
        headers: dict[str, str],
        body: bytes | None,
        latency_ms: float,
    ) -> None:
        """結合 Request 上下文記錄完整 Response 並輸出。"""
        context["response_status"] = status
        context["response_headers"] = dict(headers)
        context["latency_ms"] = round(latency_ms, 2)

        if self.log_response_body and body:
            try:
                context["response_body"] = json.loads(body)
            except (json.JSONDecodeError, UnicodeDecodeError):
                context["response_body"] = body.decode("utf-8", errors="replace")

        self._logger.info(json.dumps(context, ensure_ascii=False, default=str))
