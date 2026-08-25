from __future__ import annotations

import threading
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class _StorefrontHandler(SimpleHTTPRequestHandler):
    def end_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return


@dataclass(slots=True)
class LocalStorefront:
    server: ThreadingHTTPServer
    thread: threading.Thread
    url: str

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


def start_local_storefront(
    directory: Path,
    host: str = "127.0.0.1",
    port: int = 8080,
    *,
    auto_open: bool = True,
    browser_opener: Callable[[str], object] = webbrowser.open,
) -> LocalStorefront:
    index_path = directory / "index.html"
    if not index_path.is_file():
        raise FileNotFoundError(f"Splitzzz website was not found at {index_path}")

    handler = partial(_StorefrontHandler, directory=str(directory))
    server = ThreadingHTTPServer((host, port), handler)
    actual_port = int(server.server_address[1])
    public_host = "localhost" if host in {"127.0.0.1", "0.0.0.0"} else host
    url = f"http://{public_host}:{actual_port}"
    thread = threading.Thread(
        target=server.serve_forever,
        name="splitzzz-storefront",
        daemon=True,
    )
    thread.start()
    if auto_open:
        browser_opener(url)
    return LocalStorefront(server=server, thread=thread, url=url)
