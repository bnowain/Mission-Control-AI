"""
Mission Control -- Startup Script
=================================
Prefers port 8860 (registered in root CLAUDE.md).
Cleans up any stale processes on 8860-8869 before starting.
If 8860 is still busy after cleanup, auto-increments to a free port.
Opens the browser once the server is ready.

Usage:
    python run.py              # backend only (port 8860+)
    python run.py --ui         # backend + frontend dev server
    python run.py --port 8862  # force a specific port
    python run.py --cleanup    # cleanup ports only, don't start
"""

from __future__ import annotations

import argparse
import re
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

PREFERRED_BACKEND_PORT  = 8860
PREFERRED_FRONTEND_PORT = 5174
MAX_PORT_ATTEMPTS       = 10
BACKEND_HOST            = "127.0.0.1"
PROJECT_ROOT            = Path(__file__).resolve().parent

# Port ranges to sweep during cleanup
_BACKEND_PORTS  = range(8860, 8870)
_FRONTEND_PORTS = range(5174, 5185)

# Regex to find the URL Vite prints: "Local:   http://localhost:5174/"
_VITE_URL_RE = re.compile(r"Local:\s+(http://localhost:\d+/?)", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Port cleanup
# ---------------------------------------------------------------------------

def _pid_on_port(port: int) -> str | None:
    """Return the PID listening on port, or None."""
    try:
        out = subprocess.check_output(
            ["netstat", "-ano"],
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        for line in out.splitlines():
            if f":{port} " in line and "LISTENING" in line:
                parts = line.split()
                if parts:
                    return parts[-1]
    except Exception:
        pass
    return None


def _kill_pid(pid: str) -> bool:
    """Force-kill a PID. Returns True if successful."""
    try:
        subprocess.run(
            ["taskkill", "/F", "/PID", pid],
            capture_output=True,
        )
        return True
    except Exception:
        return False


def cleanup_ports(ports: range | list[int], label: str = "ports") -> int:
    """Kill any processes listening on the given ports. Returns count killed."""
    killed = 0
    for port in ports:
        pid = _pid_on_port(port)
        if pid and pid != "0":
            if _kill_pid(pid):
                print(f"  Cleared port {port} (PID {pid})")
                killed += 1
    if killed == 0:
        print(f"  {label}: all clear")
    return killed


# ---------------------------------------------------------------------------
# Port helpers
# ---------------------------------------------------------------------------

def _port_free(host: str, port: int) -> bool:
    """Return True if nothing is listening on this port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) != 0


def find_free_port(host: str, preferred: int) -> int:
    """Return the first free port starting from preferred."""
    for offset in range(MAX_PORT_ATTEMPTS):
        port = preferred + offset
        if _port_free(host, port):
            if offset > 0:
                print(f"  Port {preferred} is busy - using {port} instead")
            return port
    raise RuntimeError(
        f"No free port found in range {preferred}-{preferred + MAX_PORT_ATTEMPTS - 1}. "
        "Run 'python run.py --cleanup' and try again."
    )


# ---------------------------------------------------------------------------
# Browser launcher
# ---------------------------------------------------------------------------

def _wait_then_open(backend_url: str, open_url: str, timeout: float = 30.0) -> None:
    """Poll backend /api/health, then open open_url in the browser."""
    import urllib.request

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(backend_url + "/api/health", timeout=1)
            webbrowser.open(open_url)
            print(f"  Browser opened -> {open_url}")
            return
        except Exception:
            time.sleep(0.5)
    print(f"  Server did not respond within {timeout}s -- open {open_url} manually")


# ---------------------------------------------------------------------------
# Frontend dev server
# ---------------------------------------------------------------------------

def _start_frontend() -> tuple[subprocess.Popen, str]:
    """Start Vite, parse its output to find the actual URL. Returns (proc, url)."""
    frontend_dir = PROJECT_ROOT / "frontend"
    if not frontend_dir.exists():
        print("  frontend/ directory not found -- skipping UI")
        return None, None

    print("  Starting frontend dev server...")
    proc = subprocess.Popen(
        ["npm", "run", "dev"],
        cwd=str(frontend_dir),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=True,   # required on Windows for npm
    )

    frontend_url = None
    deadline = time.monotonic() + 30.0

    def _read_vite():
        nonlocal frontend_url
        for line in proc.stdout:
            clean = re.sub(r"\x1b\[[0-9;]*m", "", line)
            m = _VITE_URL_RE.search(clean)
            if m:
                frontend_url = m.group(1).rstrip("/")

    threading.Thread(target=_read_vite, daemon=True).start()

    while frontend_url is None and time.monotonic() < deadline:
        time.sleep(0.2)

    if frontend_url:
        print(f"  Frontend ready -> {frontend_url}")
    else:
        print("  Frontend URL not detected -- Vite may still be starting")
        frontend_url = f"http://localhost:{PREFERRED_FRONTEND_PORT}"

    return proc, frontend_url


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Start Mission Control")
    parser.add_argument("--port",      type=int, default=None, help="Force backend port")
    parser.add_argument("--ui",        action="store_true",    help="Also start the frontend dev server")
    parser.add_argument("--no-browser",action="store_true",    help="Skip browser auto-launch")
    parser.add_argument("--no-cleanup",action="store_true",    help="Skip port cleanup on startup")
    parser.add_argument("--cleanup",   action="store_true",    help="Cleanup ports and exit")
    parser.add_argument("--reload",    action="store_true",    help="Enable uvicorn --reload")
    args = parser.parse_args()

    # --- Cleanup-only mode ---
    if args.cleanup:
        print("\n  Cleaning up Mission Control ports...")
        cleanup_ports(_BACKEND_PORTS,  "Backend ports 8860-8869")
        cleanup_ports(_FRONTEND_PORTS, "Frontend ports 5174-5184")
        print("  Done.\n")
        sys.exit(0)

    # --- Startup port cleanup ---
    if not args.no_cleanup:
        print("\n  Cleaning up stale processes...")
        cleanup_ports(_BACKEND_PORTS,  "Backend ports")
        time.sleep(0.5)   # give OS a moment to release sockets

    # --- Resolve backend port ---
    if args.port:
        port = args.port
        if not _port_free(BACKEND_HOST, port):
            print(f"  Warning: port {port} appears busy -- attempting anyway")
    else:
        port = find_free_port(BACKEND_HOST, PREFERRED_BACKEND_PORT)

    backend_url = f"http://{BACKEND_HOST}:{port}"
    print(f"\n  Mission Control backend -> {backend_url}")

    # Write the port so vite.config.ts can proxy to the correct address
    (PROJECT_ROOT / ".backend-port").write_text(str(port), encoding="utf-8")

    # --- Start frontend and discover its URL ---
    frontend_proc = None
    frontend_url  = None
    if args.ui:
        frontend_proc, frontend_url = _start_frontend()

    # --- Schedule browser open in background ---
    if not args.no_browser:
        open_url = frontend_url if frontend_url else backend_url
        threading.Thread(
            target=_wait_then_open,
            args=(backend_url, open_url),
            daemon=True,
        ).start()

    # --- Start uvicorn (blocks until Ctrl+C or shutdown) ---
    import uvicorn
    try:
        uvicorn.run(
            "app.main:app",
            host=BACKEND_HOST,
            port=port,
            reload=args.reload,
            log_level="info",
        )
    finally:
        if frontend_proc:
            frontend_proc.terminate()


if __name__ == "__main__":
    main()
