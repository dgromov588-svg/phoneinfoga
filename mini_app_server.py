#!/usr/bin/env python3
"""WSGI/script entrypoint for the Telegram Mini App server."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_mini_app_module():
    source_path = Path(__file__).with_name(".remote_universal_search_system.py")
    spec = importlib.util.spec_from_file_location("phoneinfoga_mini_app", source_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load mini app server from {source_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_mini_app_module = _load_mini_app_module()
app = _mini_app_module.app


if __name__ == "__main__":
    print("Mini App Server")
    print("===============")
    print("Starting Telegram Mini App server on http://localhost:5000")
    print()
    print("Available endpoints:")
    print("  GET  /miniapp - Telegram Mini App UI")
    print("  GET  /api/miniapp/session - Session state")
    print("  POST /api/miniapp/phone_search - Mini App phone search")
    print()
    app.run(host="0.0.0.0", port=5000, debug=True)
