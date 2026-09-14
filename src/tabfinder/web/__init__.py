"""The tabfinder web UI."""

from __future__ import annotations

from .app import create_app

__all__ = ["create_app", "serve"]


def serve(host: str = "127.0.0.1", port: int = 5000, debug: bool = False) -> None:
    """Run the web UI."""
    create_app().run(host=host, port=port, debug=debug, threaded=True)
