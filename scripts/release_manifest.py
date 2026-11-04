"""Verify the current Windows payload and record its test evidence and SHA-256."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import struct
import xml.etree.ElementTree as ET

import pefile

from release_version import ROOT, read_json, release_version

BUILD = ROOT / "desktop/src-tauri/target/release"
RELEASE = ROOT / "release"


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def icon_images(path):
    ico = path.read_bytes()
    count = struct.unpack_from("<H", ico, 4)[0]
    images = set()
    for index in range(count):
        size, offset = struct.unpack_from("<II", ico, 6 + index * 16 + 8)
        images.add(ico[offset:offset + size])
    return images


def binary_metadata(path, source_icons, machine):
    with pefile.PE(str(path), fast_load=True) as pe:
        pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_RESOURCE"]])
        assert pe.FILE_HEADER.Machine == machine, path
        resources = {entry.id: entry for entry in pe.DIRECTORY_ENTRY_RESOURCE.entries}
        assert 3 in resources and 14 in resources, f"Missing icon: {path}"
        embedded = {
            pe.get_data(entry.data.struct.OffsetToData, entry.data.struct.Size)
            for icon in resources[3].directory.entries
            for entry in icon.directory.entries
        }
        assert embedded & source_icons, f"Unexpected icon: {path}"
        signed = bool(pe.OPTIONAL_HEADER.DATA_DIRECTORY[4].Size)
    return {"bytes": path.stat().st_size, "sha256": digest(path), "authenticode_signed": signed}


def check_installer_script():
    config = read_json("desktop/src-tauri/tauri.conf.json")
    script = (BUILD / "nsis/x64/installer.nsi").read_text(encoding="utf-8")
    assert f'!define VERSION "{config["version"]}"' in script
    assert '!define INSTALLMODE "currentUser"' in script
    assert '/oname=sky-data-runtime.exe' in script
    assert 'FIRST_PARTY_LICENSE.txt' in script and 'THIRD_PARTY_NOTICES.txt' in script
    assert '!define INSTALLERICON ""' not in script and '!define UNINSTALLERICON ""' not in script

    mode = config["bundle"]["windows"]["webviewInstallMode"]
    assert mode["type"] == "fixedRuntime"
    assert '!define INSTALLWEBVIEW2MODE ""' in script
    assert '!define WEBVIEW2BOOTSTRAPPERPATH ""' in script
    app = ROOT / "desktop/src-tauri"
    runtime = app / mode["path"]
    files = {path.relative_to(app).as_posix() for path in runtime.rglob("*") if path.is_file()}
    bundled = {name.replace(chr(92), "/") for name in re.findall(r'File /a "/oname=([^"]+)"', script)}
    assert (runtime / "msedgewebview2.exe").is_file() and files <= bundled
    assert mode["path"].encode() in (BUILD / "sky-data-workspace.exe").read_bytes()
    return {"mode": mode["type"], "folder": mode["path"], "files": len(files)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native-report", type=Path, required=True)
    parser.add_argument("--ui-report", type=Path, required=True)
    parser.add_argument("--iana-report", type=Path, required=True)
    args = parser.parse_args()
    version = release_version()
    installer = RELEASE / f"SKY_Data_Workspace_{version}_x64_Setup.exe"
    app = BUILD / "sky-data-workspace.exe"
    runtime = BUILD / "sky-data-runtime.exe"
    expected_runtime = ROOT / "artifacts/frozen/sky-data-runtime.exe"
    assert digest(runtime) == digest(expected_runtime), "Staged and frozen runtimes differ"
    bundle = BUILD / "bundle/nsis" / f"SKY Data Workspace_{version}_x64-setup.exe"
    assert digest(installer) == digest(bundle), "Release installer differs from bundled installer"
    icons = icon_images(ROOT / "desktop/src-tauri/icons/icon.ico")
    binaries = {
        "installer": {"file": installer.name, **binary_metadata(installer, icons, 0x14C)},
        "desktop": binary_metadata(app, icons, 0x8664),
        "runtime": binary_metadata(runtime, icons, 0x8664),
    }

    native = json.loads(args.native_report.read_text(encoding="utf-8-sig"))
    assert native["passed"] and native["health"]["version"] == version and native["runtime_stopped"]
    assert native["app_sha256"] == binaries["desktop"]["sha256"]
    assert native["runtime_sha256"] == binaries["runtime"]["sha256"]
    ui = json.loads(args.ui_report.read_text(encoding="utf-8-sig"))
    assert ui["passed"] and ui["version"] == version and ui["headless"]
    iana = json.loads(args.iana_report.read_text(encoding="utf-8-sig"))
    assert iana["passed"] and iana["version"] == version and iana["official_csv_match"]
    assert iana["app_sha256"] == binaries["desktop"]["sha256"]
    assert iana["runtime_sha256"] == binaries["runtime"]["sha256"]
    suites = ET.parse(ROOT / "artifacts/tests/desktop-backend.xml").getroot().findall("testsuite")
    assert suites and all(int(suite.get("failures", 0)) + int(suite.get("errors", 0)) == 0 for suite in suites)
    report = {
        "version": version,
        "recorded_utc": datetime.now(timezone.utc).isoformat(),
        "binaries": binaries,
        "webview2": check_installer_script(),
        "checks": {
            "backend_tests": sum(int(suite.get("tests", 0)) for suite in suites),
            "native_no_window": True,
            "ui_headless_cases": len(ui["cases"]),
            "iana_csv_rows_matched": iana["rows"],
            "native_window_and_sandbox_tested_for_this_release": False,
        },
    }
    output = RELEASE / f"SKY_Data_Workspace_{version}_manifest.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    checksum = RELEASE / f"SKY_Data_Workspace_{version}_SHA256.txt"
    checksum.write_text(f"{binaries['installer']['sha256']}  {installer.name}\n", encoding="ascii")
    print(json.dumps(report, ensure_ascii=True))


if __name__ == "__main__":
    main()
