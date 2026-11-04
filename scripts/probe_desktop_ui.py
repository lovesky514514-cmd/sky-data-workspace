"""Run the desktop browser acceptance suite against an isolated frozen runtime."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4

import httpx

from release_version import ROOT, release_version


def wait_for_preview(server):
    with httpx.Client(trust_env=False, timeout=2) as client:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if server.poll() is not None:
                raise RuntimeError("Vite stopped before the preview was ready")
            try:
                if client.get("http://127.0.0.1:5178/").is_success:
                    return
            except httpx.TransportError:
                pass
            time.sleep(.2)
    raise TimeoutError("Vite preview did not start")


def stop_runtime(session_file):
    if not session_file.is_file():
        return
    session = json.loads(session_file.read_text(encoding="utf-8"))
    try:
        response = httpx.post(session["base_url"] + "/api/shutdown",
                              headers={"Authorization": "Bearer " + session["token"]},
                              json={}, trust_env=False, timeout=5)
        response.raise_for_status()
    except httpx.TransportError:
        pass  # The isolated runtime has already exited.


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser", type=Path, help="Optional installed Chromium headless executable")
    args = parser.parse_args()
    version = release_version()
    desktop = ROOT / "desktop"
    acceptance = ROOT / f"artifacts/acceptance/{version}"
    data = acceptance / f"browser-runtime-{uuid4().hex[:8]}"
    session_file = data / "runtime.json"
    acceptance.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ, SKY_PREVIEW_RUNTIME=str(session_file),
                       SKY_UI_REPORT_DIR=str(acceptance / "ui"))
    if args.browser:
        environment["SKY_HEADLESS_BROWSER"] = str(args.browser.resolve(strict=True))
    try:
        subprocess.run([sys.executable, str(ROOT / "scripts/probe_frozen_runtime.py"),
                        "--data-dir", str(data), "--report", str(acceptance / "frozen.json"),
                        "--leave-running"], check=True, timeout=150)
        with (acceptance / "vite.log").open("w", encoding="utf-8") as log:
            server = subprocess.Popen(["node", "node_modules/vite/bin/vite.js"],
                cwd=desktop, env=environment, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                creationflags=subprocess.CREATE_NO_WINDOW)
            try:
                wait_for_preview(server)
                subprocess.run(["node", "tests/ui.smoke.mjs"], cwd=desktop, env=environment,
                               check=True, timeout=150)
            finally:
                if server.poll() is None:
                    server.terminate()
                    server.wait(timeout=10)
    finally:
        stop_runtime(session_file)
    result = json.loads((acceptance / "ui/report.json").read_text(encoding="utf-8"))
    assert result["passed"] and result["version"] == version
    print(f"{len(result['cases'])} headless interface cases passed for {version}")


if __name__ == "__main__":
    main()
