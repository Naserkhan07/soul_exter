"""Run the entirely local links.txt automation from VS Code or a terminal."""

import sys

if sys.version_info >= (3, 14):
    raise SystemExit(
        "Python 3.14 is not supported by the Chrome PO-token provider. "
        "Run: .\\.venv\\Scripts\\python.exe main.py"
    )

from shorts_bot.file_queue import main  # noqa: E402

if __name__ == "__main__":
    main()
