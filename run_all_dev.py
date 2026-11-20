
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time
import asyncio, os, signal, subprocess, sys, time
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings


ROOT = Path(__file__).resolve().parent


async def verify_dev_database(database_url: str) -> None:
    engine = create_async_engine(database_url, pool_pre_ping=True)

    try:
        async with engine.connect() as connection:
            database = await connection.scalar(
                text("SELECT current_database()")
            )

            if database != "medi_dev":
                raise RuntimeError(
                    f"Refusing to start: expected medi_dev, got {database}."
                )

            print("Verified database: medi_dev", flush=True)
    finally:
        await engine.dispose()


def stop_processes(processes):
    # First request graceful shutdown for each process group.
    for name, process in processes:
        if process.poll() is None:
            print(f"Stopping {name} gracefully...", flush=True)
            try:
                process.send_signal(signal.CTRL_BREAK_EVENT)
            except (OSError, ValueError):
                pass

    # Wait for graceful shutdown.
    for name, process in processes:
        if process.poll() is None:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                print(f"Force stopping {name} process tree...", flush=True)
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                process.wait()

    print("All MEDI development services stopped.", flush=True)
    for name, process in processes:
        if process.poll() is None:
            print(f"Stopping {name}...", flush=True)
            process.terminate()

    for name, process in processes:
        if process.poll() is None:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                print(f"Force stopping {name}...", flush=True)
                process.kill()
                process.wait()


def main() -> int:
    if settings.ENVIRONMENT.lower() != "development":
        raise RuntimeError(
            "Development supervisor requires ENVIRONMENT=development."
        )

    database_url = make_url(settings.DATABASE_URL)

    if database_url.host not in {"localhost", "127.0.0.1", "::1"}:
        raise RuntimeError(
            "Refusing to start: development database host must be local."
        )

    dev_url = database_url.set(database="medi_dev")
    runtime_database_url = dev_url.render_as_string(
        hide_password=False
    )

    asyncio.run(verify_dev_database(runtime_database_url))

    child_env = os.environ.copy()
    child_env["DATABASE_URL"] = runtime_database_url
    child_env["ENVIRONMENT"] = "development"

    commands = [
        (
            "API Server",
            [
                sys.executable, "-m", "uvicorn",
                "app.main:app",
                "--host", "127.0.0.1",
                "--port", "8000",
                "--reload",
                "--reload-dir", "app",
            ],
        ),
        (
            "Reminder Worker",
            [
                sys.executable, "-m",
                "app.workers.reminder_worker",
            ],
        ),
        (
            "Notification Worker",
            [
                sys.executable, "-m",
                "app.workers.notification_worker",
            ],
        ),
    ]

    processes: list[tuple[str, subprocess.Popen]] = []

    try:
        for name, command in commands:
            print(f"Starting {name}...", flush=True)

            process = subprocess.Popen(
                command,
                cwd=ROOT,
                env=child_env,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
            )

            processes.append((name, process))

        print(
            "MEDI development services are running. "
            "Press Ctrl+C to stop all services.",
            flush=True,
        )

        while True:
            time.sleep(1)

            for name, process in processes:
                exit_code = process.poll()

                if exit_code is not None:
                    print(
                        f"{name} stopped unexpectedly "
                        f"(exit code {exit_code}).",
                        flush=True,
                    )
                    return exit_code or 1

    except KeyboardInterrupt:
        print("\nShutdown requested.", flush=True)
        return 0

    finally:
        stop_processes(processes)
        print("All MEDI development services stopped.", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
