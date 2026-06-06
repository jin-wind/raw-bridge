"""Header injection engine for dynamically managing proxied request headers."""

from __future__ import annotations

from typing import Any


class HeaderInjector:
    """Apply configured header injection, override, and filtering rules.

    使用方式：
        injector = HeaderInjector(config)
        headers = injector.apply(original_headers)
    """

    def __init__(self, config: dict[str, Any]) -> None:
        hdr_cfg = config.get("headers", {})
        self._inject: dict[str, str] = dict(hdr_cfg.get("inject", {}))
        self._override: bool = hdr_cfg.get("override_original", True)
        self._passthrough_whitelist: list[str] = hdr_cfg.get("passthrough_whitelist", [])

    def add_rule(self, key: str, value: str) -> None:
        """Add or update one injection rule."""
        self._inject[key] = value

    def remove_rule(self, key: str) -> None:
        """Remove one injection rule."""
        existing = self._find_header_key(self._inject, key)
        if existing is not None:
            self._inject.pop(existing, None)

    def set_passthrough_whitelist(self, keys: list[str]) -> None:
        """Set a whitelist for original request headers."""
        self._passthrough_whitelist = keys

    @property
    def rules(self) -> dict[str, str]:
        """Return a copy of the current injection rules."""
        return dict(self._inject)

    def apply(self, original_headers: dict[str, str]) -> dict[str, str]:
        """Apply injection rules to original headers and return final headers."""
        if self._passthrough_whitelist:
            allowed = {key.lower() for key in self._passthrough_whitelist}
            base = {
                k: v
                for k, v in original_headers.items()
                if k.lower() in allowed
            }
        else:
            base = dict(original_headers)

        if self._override:
            for key, value in self._inject.items():
                existing = self._find_header_key(base, key)
                if existing is not None:
                    base.pop(existing, None)
                base[key] = value
        else:
            for k, v in self._inject.items():
                if self._find_header_key(base, k) is None:
                    base[k] = v

        return base

    @staticmethod
    def _find_header_key(headers: dict[str, str], key: str) -> str | None:
        lowered = key.lower()
        return next((candidate for candidate in headers if candidate.lower() == lowered), None)
