"""Start the local Splitzzz storefront and links.txt automation together."""

from __future__ import annotations

import os
import sys
from pathlib import Path

if sys.version_info >= (3, 14):
    raise SystemExit(
        "Python 3.14 is not supported by the Chrome PO-token provider. "
        "Run: .\\.venv\\Scripts\\python.exe main.py"
    )

from dotenv import load_dotenv  # noqa: E402

from shorts_bot.file_queue import main as queue_main  # noqa: E402
from shorts_bot.local_site import LocalStorefront, start_local_storefront  # noqa: E402


def _enabled(name: str, default: bool = True) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().casefold() in {"1", "true", "yes", "on"}


def _start_website() -> LocalStorefront | None:
    if not _enabled("START_LOCAL_WEBSITE"):
        return None

    project_root = Path(__file__).resolve().parent
    configured_directory = os.getenv("LOCAL_WEBSITE_DIRECTORY", "website/public")
    directory = Path(configured_directory).expanduser()
    if not directory.is_absolute():
        directory = project_root / directory

    try:
        preferred_port = int(os.getenv("LOCAL_WEBSITE_PORT", "8080"))
    except ValueError:
        preferred_port = 8080
    preferred_port = min(65535, max(1, preferred_port))
    host = os.getenv("LOCAL_WEBSITE_HOST", "127.0.0.1").strip() or "127.0.0.1"
    auto_open = _enabled("LOCAL_WEBSITE_AUTO_OPEN")

    for port in range(preferred_port, min(65536, preferred_port + 10)):
        try:
            website = start_local_storefront(
                directory,
                host,
                port,
                auto_open=auto_open,
            )
            print(f"Splitzzz website started: {website.url}", flush=True)
            return website
        except OSError as exc:
            if port + 1 >= min(65536, preferred_port + 10):
                print(f"Splitzzz website could not start: {exc}", file=sys.stderr, flush=True)
        except FileNotFoundError as exc:
            print(str(exc), file=sys.stderr, flush=True)
            return None
    return None


def main() -> None:
    load_dotenv()
    website = _start_website()
    try:
        queue_main()
    finally:
        if website:
            website.stop()


if __name__ == "__main__":
    main()
