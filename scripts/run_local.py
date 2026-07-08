from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from http.client import HTTPConnection
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_PATH = PROJECT_ROOT / "src"
NO_PROXY = "localhost,127.0.0.1,0.0.0.0,::1"
PROJECT_PYTHON = PROJECT_ROOT / ".venv" / "bin" / "python"


def main() -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC_PATH)
    env["NO_PROXY"] = NO_PROXY
    env["no_proxy"] = NO_PROXY
    env["AGENT_URL"] = "http://127.0.0.1:8080"
    env["MODE"] = "local"

    processes: list[subprocess.Popen[bytes]] = []
    python = str(PROJECT_PYTHON if PROJECT_PYTHON.exists() else Path(sys.executable))
    try:
        processes.append(
            start_process("agent-service", [python, str(SRC_PATH / "run_service.py")], env)
        )
        wait_for_backend(host="127.0.0.1", port=8080, path="/health")
        processes.append(
            start_process(
                "streamlit-app",
                [
                    python,
                    "-m",
                    "streamlit",
                    "run",
                    str(SRC_PATH / "streamlit_app.py"),
                    "--server.port",
                    "8501",
                    "--server.address",
                    "0.0.0.0",
                ],
                env,
            )
        )

        print("\nAgent service: http://localhost:8080")
        print("Streamlit app: http://localhost:8501")
        print("Press Ctrl+C to stop both.\n")

        while all(process.poll() is None for process in processes):
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nStopping local services...")
    finally:
        stop_processes(processes)


def start_process(name: str, command: list[str], env: dict[str, str]) -> subprocess.Popen[bytes]:
    print(f"Starting {name}: {' '.join(command)}")
    return subprocess.Popen(command, cwd=PROJECT_ROOT, env=env, start_new_session=True)


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
