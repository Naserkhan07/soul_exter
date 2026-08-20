#!/usr/bin/env python3
"""Run Automaton locally and expose it through a temporary Cloudflare Quick Tunnel.

Requires the `cloudflared` executable to be installed and available on PATH. The
public URL is temporary and normally changes every time this script starts.
"""

import argparse
import os
import queue
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.request

URL_PATTERN = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


def start_server(port: int, public_url: str | None = None) -> subprocess.Popen:
    env = os.environ.copy()
    env.setdefault("DATABASE_PATH", "data/automaton.db")
    if public_url:
        env["PUBLIC_BASE_URL"] = public_url
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", str(port)],
        env=env,
    )


def stop(process: subprocess.Popen | None) -> None:
    if not process or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def wait_for_local(port: int, timeout: int = 30) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(0.25)
    raise RuntimeError("The local Automaton server did not become healthy.")


def stream_output(process: subprocess.Popen, output: queue.Queue[str]) -> None:
    assert process.stdout is not None
    for line in process.stdout:
        print(f"[tunnel] {line}", end="")
        output.put(line)


def main() -> int:
    parser = argparse.ArgumentParser(description="Expose local Automaton through a temporary public HTTPS tunnel.")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--timeout", type=int, default=60, help="Seconds to wait for a public URL")
    args = parser.parse_args()

    cloudflared = shutil.which("cloudflared")
    if not cloudflared:
        print("cloudflared was not found on PATH. Install it from https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/", file=sys.stderr)
        return 2

    server: subprocess.Popen | None = None
    tunnel: subprocess.Popen | None = None
    shutting_down = False

    def cleanup(*_args) -> None:
        nonlocal shutting_down
        if shutting_down:
            return
        shutting_down = True
        stop(tunnel)
        stop(server)

    signal.signal(signal.SIGINT, cleanup)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, cleanup)

    try:
        server = start_server(args.port)
        wait_for_local(args.port)
        tunnel = subprocess.Popen(
            [cloudflared, "tunnel", "--url", f"http://127.0.0.1:{args.port}", "--no-autoupdate"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        lines: queue.Queue[str] = queue.Queue()
        threading.Thread(target=stream_output, args=(tunnel, lines), daemon=True).start()

        public_url = None
        deadline = time.time() + args.timeout
        while time.time() < deadline and tunnel.poll() is None:
            try:
                line = lines.get(timeout=1)
            except queue.Empty:
                continue
            match = URL_PATTERN.search(line)
            if match:
                public_url = match.group(0)
                break
        if not public_url:
            raise RuntimeError("Cloudflare did not provide a public URL.")

        # Restart once so checkout redirects, delivery links, robots, and sitemap use
        # the tunnel origin rather than localhost.
        stop(server)
        server = start_server(args.port, public_url)
        wait_for_local(args.port)

        print("\nAutomaton is public temporarily:")
        print(public_url)
        print("PhonePe webhook URL:")
        print(f"{public_url}/webhooks/phonepe")
        print("\nKeep this terminal open. Ctrl+C stops both the server and tunnel.")
        print("The URL usually changes after restart; update the PhonePe webhook before accepting payments.\n")

        while not shutting_down:
            if server.poll() is not None:
                raise RuntimeError(f"Automaton exited with code {server.returncode}")
            if tunnel.poll() is not None:
                raise RuntimeError(f"Cloudflare tunnel exited with code {tunnel.returncode}")
            time.sleep(1)
        return 0
    except Exception as exc:
        print(f"Failed: {exc}", file=sys.stderr)
        return 1
    finally:
        cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
