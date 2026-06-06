"""請求 Body 標準化器 — 自動偵測 Content-Type 並轉換為 JSON。"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import parse_qs


def normalize_body(
    body: bytes | None,
    content_type: str,
) -> tuple[bytes, str]:
    """將各種格式的 Request Body 標準化為 JSON。

    Returns:
        (normalized_bytes, new_content_type)

    支援的輸入格式：
        - application/json          → 原樣回傳（pretty-print）
        - application/x-www-form-urlencoded → 轉換為 JSON
        - text/plain（若內容為 JSON 字串）→ 解析後重新序列化
        - 其他 → 原樣回傳
    """
    if body is None or len(body) == 0:
        return b"", "application/json"

    ct = content_type.lower().split(";")[0].strip()

    # ── 已經是 JSON ──────────────────────────────────────────────
    if ct == "application/json":
        try:
            parsed = json.loads(body)
            return (
                json.dumps(parsed, ensure_ascii=False, indent=2).encode("utf-8"),
                "application/json",
            )
        except (json.JSONDecodeError, UnicodeDecodeError):
            return body, content_type

    # ── Form URL-Encoded ─────────────────────────────────────────
    if ct == "application/x-www-form-urlencoded":
        try:
            qs = parse_qs(body.decode("utf-8"))
            # parse_qs 回傳每個 key 都是 list；單值時展開
            result = {k: v[0] if len(v) == 1 else v for k, v in qs.items()}
            return (
                json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8"),
                "application/json",
            )
        except (UnicodeDecodeError, ValueError):
            return body, content_type

    # ── Plain Text（嘗試當 JSON 解析）────────────────────────────
    if ct == "text/plain":
        try:
            parsed = json.loads(body)
            return (
                json.dumps(parsed, ensure_ascii=False, indent=2).encode("utf-8"),
                "application/json",
            )
        except (json.JSONDecodeError, UnicodeDecodeError):
            # 非 JSON 純文字，包裝成 {"raw": "..."}
            wrapper = {"raw": body.decode("utf-8", errors="replace")}
            return (
                json.dumps(wrapper, ensure_ascii=False, indent=2).encode("utf-8"),
                "application/json",
            )

    # ── 其他格式 → 原樣回傳 ──────────────────────────────────────
    return body, content_type
