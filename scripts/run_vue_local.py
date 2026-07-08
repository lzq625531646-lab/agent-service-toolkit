from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
from http.client import HTTPConnection
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_PATH = PROJECT_ROOT / "src"
VUE_ROOT = PROJECT_ROOT / "vue-frontend"
NO_PROXY = "localhost,127.0.0.1,0.0.0.0,::1"
PROJECT_PYTHON = PROJECT_ROOT / ".venv" / "bin" / "python"


def main() -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC_PATH)
    env["NO_PROXY"] = NO_PROXY
    env["no_proxy"] = NO_PROXY
    env["MODE"] = "local"
    env["VITE_API_BASE_URL"] = "http://localhost:8080"

    python = str(PROJECT_PYTHON if PROJECT_PYTHON.exists() else Path(sys.executable))
    processes: list[subprocess.Popen[bytes]] = []
    try:
        ensure_port_available(8080)
        ensure_port_available(5173)
        ensure_npm_dependencies()
        processes.append(
            start_process(
                "agent-service",
                [python, str(SRC_PATH / "run_service.py")],
                PROJECT_ROOT,
                env,
            )
        )
        wait_for_backend(host="127.0.0.1", port=8080, path="/health")
        processes.append(
            start_process(
                "vue-frontend",
                ["npm", "run", "dev"],
                VUE_ROOT,
                env,
            )
        )

        print("\nAgent service: http://localhost:8080")
        print("Vue frontend: http://localhost:5173")
        print("Press Ctrl+C to stop both.\n")

        while all(process.poll() is None for process in processes):
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nStopping local services...")
    finally:
        stop_processes(processes)


def start_process(
    name: str, command: list[str], cwd: Path, env: dict[str, str]
) -> subprocess.Popen[bytes]:
    print(f"Starting {name}: {' '.join(command)}")
    return subprocess.Popen(command, cwd=cwd, env=env, start_new_session=True)


def ensure_port_available(port: int) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        if sock.connect_ex(("127.0.0.1", port)) == 0:
            raise RuntimeError(f"Port {port} is already in use. Stop it before running this script.")


def ensure_npm_dependencies() -> None:
    if (VUE_ROOT / "node_modules").exists():
        return
    print("Installing Vue frontend dependencies...")
    subprocess.run(["npm", "install"], cwd=VUE_ROOT, check=True)


def wait_for_backend(host: str, port: int, path: str, timeout_seconds: float = 60.0) -> None:
    deadline = time.time() + timeout_seconds
    last_error: Exception | None = None
    while time.time() < deadline:
        connection: HTTPConnection | None = None
        try:
            connection = HTTPConnection(host, port, timeout=1)
            connection.request("GET", path)
            response = connection.getresponse()
            if response.status == 200:
                return
        except Exception as exc:
            last_error = exc
            time.sleep(0.5)
        finally:
            if connection:
                connection.close()
    detail = f" Last error: {last_error}" if last_error else ""
    raise RuntimeError(f"Backend did not become healthy: http://{host}:{port}{path}.{detail}")


def stop_processes(processes: list[subprocess.Popen[bytes]]) -> None:
    for process in processes:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)

    deadline = time.time() + 8
    for process in processes:
        while process.poll() is None and time.time() < deadline:
            time.sleep(0.2)
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)


if __name__ == "__main__":
    main()
