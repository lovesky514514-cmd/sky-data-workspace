"""Validate the packaged Rust host and its adjacent sidecar without creating a window."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess

from release_version import ROOT, release_version


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    version = release_version()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-dir", type=Path, default=ROOT / "desktop/src-tauri/target/release")
    parser.add_argument("--report", type=Path, default=ROOT / f"artifacts/acceptance/{version}/native.json")
    args = parser.parse_args()
    report = args.report.resolve()
    report.parent.mkdir(parents=True, exist_ok=True)
    app = args.app_dir.resolve() / "sky-data-workspace.exe"
    runtime = app.with_name("sky-data-runtime.exe")
    app_hash, runtime_hash = digest(app), digest(runtime)
    subprocess.run([
        str(app), "--headless-check", "--data-dir", str(report.parent / "中文用户 路径"),
        "--report", str(report),
    ], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW, timeout=100, check=True)
    result = json.loads(report.read_text(encoding="utf-8"))
    assert result["passed"] and result["health"]["version"] == version, result["health"]
    if (app_hash, runtime_hash) != (digest(app), digest(runtime)):
        raise RuntimeError("Packaged binaries changed during the check. Run it after the build completes.")
    result.update(app_sha256=app_hash, runtime_sha256=runtime_hash)
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Native {version} backend startup and shutdown passed. Report: {report}")


if __name__ == "__main__":
    main()
