"""Check that package metadata agrees with the Tauri release version."""

import json
from pathlib import Path
from runpy import run_path
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def read_json(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def read_toml(path):
    return tomllib.loads((ROOT / path).read_text(encoding="utf-8"))


def release_version():
    version = read_json("desktop/src-tauri/tauri.conf.json")["version"]
    npm_lock = read_json("desktop/package-lock.json")
    rust_lock = read_toml("desktop/src-tauri/Cargo.lock")
    runtime_module = ROOT / "backend/sky_data_workspace/__init__.py"
    runtime_metadata = run_path(str(runtime_module))
    versions = {
        "desktop/package.json": read_json("desktop/package.json")["version"],
        "desktop/package-lock.json": npm_lock["version"],
        "npm root package lock": npm_lock["packages"][""]["version"],
        "desktop/src-tauri/Cargo.toml": read_toml("desktop/src-tauri/Cargo.toml")["package"]["version"],
        "Rust root package lock": next(p["version"] for p in rust_lock["package"] if p["name"] == "sky-data-workspace"),
        "backend/pyproject.toml": read_toml("backend/pyproject.toml")["project"]["version"],
        "Python runtime": runtime_metadata["__version__"],
    }
    mismatches = [f"{path}: {value}" for path, value in versions.items() if value != version]
    if mismatches:
        raise ValueError(f"Expected release version {version}. Mismatches: " + ", ".join(mismatches))
    return version


if __name__ == "__main__":
    print(release_version())
