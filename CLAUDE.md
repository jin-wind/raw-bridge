# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

raw-bridge is a local reverse proxy built with aiohttp. It intercepts HTTP requests, injects configured headers (e.g. spoofing a specific client identity), normalizes request bodies to JSON, logs traffic, and forwards everything to a configurable upstream target.

Primary use case: routing Claude Code requests through a local proxy that rewrites headers so the upstream API sees a permitted client fingerprint.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run the proxy (default: 127.0.0.1:8080, config from config.yaml)
python main.py
python main.py --config custom.yaml --port 9090 --target https://example.com

# Run all tests
pytest

# Run a single test
pytest tests/test_proxy.py::test_json_normalization_keeps_valid_payload
```

## Architecture

All proxy logic lives in `proxy/`. The entry point is `main.py` which loads YAML config and starts the aiohttp app.

**Request flow:**
1. `server.py` — `ReverseProxy.handle()` receives every incoming request (catch-all route `/{path_info:.*}`)
2. `normalizer.py` — `normalize_body()` converts form-encoded or plain-text bodies to JSON; passes JSON through as-is
3. `middleware.py` — `HeaderInjector.apply()` strips original headers to a whitelist, then overlays injected headers (with optional override)
4. `logger.py` — `TrafficLogger` records request/response as structured JSON to both console and `logs/proxy.log`
5. `server.py` — forwards the rewritten request to `target_base_url + original path`, streams the response back

**Key config knobs** (in `config.yaml`):
- `proxy.target_base_url` — upstream URL all requests are forwarded to
- `headers.inject` — key/value map of headers to add/replace
- `headers.override_original` — when `true`, injected headers replace existing ones; when `false`, injected headers only fill missing ones
- `headers.passthrough_whitelist` — only these original request headers survive; everything else is dropped before injection
