#!/usr/bin/env python3
"""raw-bridge 本地轉發中間件 — 啟動入口。

使用方式：
    python main.py                     # 使用預設 config.yaml
    python main.py --config my.yaml    # 指定配置檔
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from proxy.server import ReverseProxy, create_app


def load_config(config_path: str) -> dict:
    """載入 YAML 配置檔。"""
    path = Path(config_path)
    if not path.exists():
        print(f"⚠️  配置檔不存在: {config_path}，使用預設值")
        return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="raw-bridge 本地轉發中間件",
    )
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="配置檔路徑 (預設: config.yaml)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="覆蓋配置中的 listen_port",
    )
    parser.add_argument(
        "--target",
        default=None,
        help="覆蓋配置中的 target_base_url",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_config(args.config)

    # 允許 CLI 參數覆蓋配置
    if args.port:
        config.setdefault("proxy", {})["listen_port"] = args.port
    if args.target:
        config.setdefault("proxy", {})["target_base_url"] = args.target

    proxy_cfg = config.get("proxy", {})

    from aiohttp import web

    web.run_app(
        create_app(config),
        host=proxy_cfg.get("listen_host", "127.0.0.1"),
        port=int(proxy_cfg.get("listen_port", 8080)),
    )


if __name__ == "__main__":
    main()
