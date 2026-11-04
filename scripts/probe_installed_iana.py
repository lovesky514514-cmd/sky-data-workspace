"""Collect the live IANA table through the installed app and verify its own Excel export."""

import argparse
import csv
import hashlib
import io
import json
import os
import re
import time
import zipfile
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit
from xml.etree import ElementTree

import httpx

from release_version import ROOT, release_version

SOURCE = "https://www.iana.org/assignments/http-status-codes/http-status-codes.xhtml"
OFFICIAL_CSV = "https://www.iana.org/assignments/http-status-codes/http-status-codes-1.csv"
FIELDS = ["Value", "Description", "Reference"]
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def read_workbook(payload):
    with zipfile.ZipFile(io.BytesIO(payload)) as book:
        assert book.testzip() is None
        workbook = ElementTree.fromstring(book.read("xl/workbook.xml"))
        names = [sheet.attrib["name"] for sheet in workbook.findall("m:sheets/m:sheet", NS)]
        assert names == ["采集数据", "来源信息", "质量与审核"], names
        sheet = ElementTree.fromstring(book.read("xl/worksheets/sheet1.xml"))
        assert sheet.find(".//m:f", NS) is None
        rows = []
        for row in sheet.findall("m:sheetData/m:row", NS):
            values = {}
            for cell in row.findall("m:c", NS):
                column = re.match(r"[A-Z]+", cell.attrib["r"])[0]
                values[column] = "".join(node.text or "" for node in cell.findall(".//m:t", NS))
            rows.append(values)
    return names, [{header: row.get(column, "") for column, header in rows[0].items()} for row in rows[1:]]


def official_row(row):
    # IANA adds brackets around references in its CSV, and uses link text in HTML.
    reference = re.sub(r"[\s\[\]]+", "", row["Reference"] or "")
    return row["Value"].strip(), " ".join(row["Description"].split()), reference


def main():
    version = release_version()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path(os.environ["APPDATA"]) / "io.sky.dataworkspace")
    parser.add_argument("--app-dir", type=Path, default=Path(os.environ["LOCALAPPDATA"]) / "SKY Data Workspace")
    parser.add_argument("--report", type=Path, default=ROOT / f"artifacts/acceptance/{version}/iana.json")
    parser.add_argument("--output", type=Path, default=ROOT / f"release/IANA_HTTP_Status_Codes_{version}.xlsx")
    args = parser.parse_args()
    data_dir = args.data_dir
    info = json.loads((data_dir / "runtime.json").read_text(encoding="utf-8-sig"))
    base = urlsplit(info["base_url"])
    assert (base.scheme, base.hostname) == ("http", "127.0.0.1") and base.port

    with httpx.Client(base_url=info["base_url"], headers={"Authorization": "Bearer " + info["token"]},
                      trust_env=False, timeout=75) as app:
        def request(path, body=None):
            response = app.get(path) if body is None else app.post(path, json=body)
            if response.is_error:
                raise RuntimeError(f"{path} returned {response.status_code}: {response.text[:1000]}")
            return response.json()

        health = request("/api/health")
        assert health["version"] == version and health["runtime"] == "running", health
        preview = request("/api/tasks/preview", {"url": SOURCE})
        assert set(FIELDS).issubset(preview["fields"]), preview["fields"]
        task_name = f"IANA HTTP Status Codes - {version} native runtime test"
        task = request("/api/tasks", {"name": task_name, "urls": [SOURCE], "fields": FIELDS, "interval_seconds": None})
        task_id = task["task_id"]
        request("/api/tasks/action", {"task_id": task_id, "action": "start"})
        deadline = time.monotonic() + 80
        while time.monotonic() < deadline:
            task = next(t for t in request("/api/tasks?limit=100")["tasks"] if t["task_id"] == task_id)
            if task["status"] in {"completed", "partial", "failed"}:
                break
            time.sleep(.4)
        assert task["status"] == "completed", request(f"/api/tasks/{task_id}/logs")
        records = request(f"/api/tasks/{task_id}/results?limit=100")["records"]
        assert len(records) == task["record_count"]
        meta = request("/api/tasks/export", {"task_id": task_id, "format": "xlsx"})
        response = app.get("/api/exports/" + meta["export_id"])
        response.raise_for_status()
        payload = response.content

    sheets, exported = read_workbook(payload)
    assert len(exported) == len(records)
    assert Counter(tuple(row[field] for field in FIELDS) for row in exported) == Counter(
        tuple(row["data"][field] or "" for field in FIELDS) for row in records)
    hashes = {row["content_hash"] for row in exported}
    assert len(hashes) == 1
    content_hash = hashes.pop()
    assert re.fullmatch(r"[a-f0-9]{64}", content_hash)
    assert all(row["source_url"].startswith("https://www.iana.org/assignments/http-status-codes")
               and row["evidence_locator"].startswith("html:table:") for row in exported)
    assert sha256((data_dir / "evidence" / f"{content_hash}.bin").read_bytes()) == content_hash

    with httpx.Client(trust_env=False, follow_redirects=True, timeout=30) as client:
        response = client.get(OFFICIAL_CSV)
        response.raise_for_status()
        official = list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))
    actual_rows = Counter(official_row(row) for row in exported)
    expected_rows = Counter(official_row(row) for row in official)
    assert actual_rows == expected_rows, {"xlsx_rows": len(exported), "official_rows": len(official),
        "missing": list((expected_rows - actual_rows).items())[:4], "extra": list((actual_rows - expected_rows).items())[:4]}

    app_dir = args.app_dir
    app_hash = sha256((app_dir / "sky-data-workspace.exe").read_bytes())
    runtime_hash = sha256((app_dir / "sky-data-runtime.exe").read_bytes())
    assert app_hash == sha256((ROOT / "desktop/src-tauri/target/release/sky-data-workspace.exe").read_bytes())
    assert runtime_hash == sha256((ROOT / "artifacts/frozen/sky-data-runtime.exe").read_bytes())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(payload)
    report = {"passed": True, "version": health["version"], "task_id": task_id, "website": SOURCE,
              "test_mode": "packaged sidecar" if args.app_dir == ROOT / "desktop/src-tauri/target/release" else "installed app API",
              "verification_csv": OFFICIAL_CSV, "preview_rows_before_field_filter": preview["total_rows"],
              "rows": len(exported), "columns_checked": FIELDS, "sheets": sheets, "official_csv_match": True,
              "source_content_sha256": content_hash,
              "app_sha256": app_hash, "runtime_sha256": runtime_hash, "workbook_sha256": sha256(payload)}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True))


if __name__ == "__main__":
    main()
