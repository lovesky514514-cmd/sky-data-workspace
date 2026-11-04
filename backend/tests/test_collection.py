import hashlib
import json
import socket
import sqlite3
import threading
import time
import zipfile

import pytest

from sky_data_workspace.extraction import extract
from sky_data_workspace.exporting import Exporter
from sky_data_workspace.fetching import public_addresses, normalize_url, SafeDownloader
from sky_data_workspace.ollama_client import AIError
from sky_data_workspace.storage import RuntimeStore
from sky_data_workspace.tasks import TaskManager, TaskDefinition

HTML = '<html><title>人工标注样例</title><table><tr><th>名称</th><th>金额</th></tr><tr><td>项目A</td><td>1,234.56</td></tr><tr><td>=HYPERLINK("x")</td><td>(12.34)</td></tr></table></html>'.encode()


def wait_for(manager, task_id, states=("completed", "partial", "failed"), timeout=6):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        task = manager.get(task_id)
        if task["status"] in states:
            return task
        time.sleep(.02)
    raise AssertionError(manager.get(task_id))


class FixtureDownloader:
    def __init__(self):
        self.calls = 0

    def fetch(self, url, check=lambda: None):
        check()
        self.calls += 1
        if "fail" in url:
            raise AIError("http_error", "来源返回HTTP 403")
        return {"url": url, "content": HTML, "content_type": "text/html; charset=utf-8"}


@pytest.fixture
def manager(tmp_path):
    instance = TaskManager(RuntimeStore(tmp_path))
    instance.downloader = FixtureDownloader()
    yield instance
    instance.close()


def make_task(manager, **changes):
    return manager.create(TaskDefinition(name="人工标注采集样例", urls=["https://example.com/a"], **changes))


def test_html_json_csv_xml_and_precision():
    parsed = extract(HTML, "text/html; charset=utf-8", "https://example.com")
    assert parsed["rows"][0]["data"] == {"名称": "项目A", "金额": "1,234.56"}
    assert parsed["rows"][0]["locator"] == "html:table:1/row:2"
    assert extract(b'[{"amount":12345678901234567890.12}]', "application/json", "https://example.com")["rows"][0]["data"]["amount"] == "12345678901234567890.12"
    assert extract("名称,值\n中文,123\n".encode(), "text/csv", "https://example.com")["rows"][0]["data"] == {"名称":"中文","值":"123"}
    assert extract(b"<root><item><name>A</name><value>1</value></item></root>", "application/xml", "https://example.com")["rows"][0]["data"] == {"name":"A","value":"1"}


def test_xml_external_entities_not_expanded():
    with pytest.raises(Exception):
        extract(b'<!DOCTYPE x [<!ENTITY xx SYSTEM "file:///C:/private">]><root><a>&xx;</a></root>', "text/xml", "https://example.com")


@pytest.mark.parametrize("address", ["127.0.0.1", "10.2.3.4", "172.16.1.1", "192.168.1.1",
                                    "169.254.169.254", "::1", "fc00::1", "100.64.0.1", "0.0.0.0"])
def test_private_and_reserved_dns_rejected(monkeypatch, address):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a,**k: [(socket.AF_INET,socket.SOCK_STREAM,6,"",(address,443))])
    with pytest.raises(AIError) as err:
        public_addresses("example.com",443)
    assert err.value.code == "blocked_address"


def test_mixed_dns_cannot_hide_private_address(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a,**k: [
        (socket.AF_INET,socket.SOCK_STREAM,6,"",("93.184.216.34",443)),
        (socket.AF_INET,socket.SOCK_STREAM,6,"",("127.0.0.1",443))])
    with pytest.raises(AIError):
        public_addresses("example.com",443)


@pytest.mark.parametrize("url", ["file:///c:/x", "http://u:p@example.com", "http://example.com:9999", "javascript:1"])
def test_dangerous_url_schemes_credentials_and_ports(url):
    with pytest.raises(ValueError):
        normalize_url(url)


def test_robots_denial_blocks_content(monkeypatch):
    downloader = SafeDownloader()
    monkeypatch.setattr(downloader, "_download", lambda *a,**kw: {"status":200,"content":b"User-agent: *\nDisallow: /private"})
    with pytest.raises(AIError) as error:
        downloader._check_robots("https://example.com/private/data", lambda: None)
    assert error.value.code == "robots_disallowed"


def test_persistence_dedup_and_raw_evidence(manager):
    task = make_task(manager)
    manager.action(task["task_id"], "start")
    assert wait_for(manager, task["task_id"])["record_count"] == 2
    rows = manager.results(task["task_id"])["records"]
    assert all(r["content_hash"] == hashlib.sha256(HTML).hexdigest() for r in rows)
    assert (manager.directory / rows[0]["raw_reference"]).read_bytes() == HTML
    assert all(r["review_status"] == "pending" for r in rows)
    manager.action(task["task_id"], "rerun")
    assert wait_for(manager, task["task_id"])["record_count"] == 2
    assert manager.store.path.is_file()


def test_partial_failure_is_not_completed(manager):
    task = manager.create(TaskDefinition(name="部分失败样例",urls=["https://example.com/a","https://example.com/fail"]))
    manager.action(task["task_id"], "start")
    result = wait_for(manager, task["task_id"])
    assert result["status"] == "partial" and result["failed"] == 1 and result["completed"] == 1
    assert any("403" in r["message"] for r in manager.logs(task["task_id"])["logs"])


def test_selected_fields_exclude_unrelated_tables(manager, monkeypatch):
    html = HTML.replace(b"</html>", b"<table><tr><th>Links</th></tr><tr><td>Home</td></tr></table></html>")
    monkeypatch.setattr(manager.downloader, "fetch", lambda url, check: {
        "url": url, "content": html, "content_type": "text/html; charset=utf-8",
    })
    task = make_task(manager, fields=["金额"])
    manager.action(task["task_id"], "start")
    assert wait_for(manager, task["task_id"])["record_count"] == 2
    records = manager.results(task["task_id"])["records"]
    assert {row["data"]["金额"] for row in records} == {"1,234.56", "(12.34)"}
    assert all(row["content_hash"] == hashlib.sha256(html).hexdigest() for row in records)

    unmatched = make_task(manager, fields=["No such column"])
    manager.action(unmatched["task_id"], "start")
    assert wait_for(manager, unmatched["task_id"])["status"] == "failed"
    assert manager.results(unmatched["task_id"])["total"] == 0


@pytest.mark.parametrize("operation,state", [("pause","paused"),("cancel","cancelled")])
def test_pause_and_cancel_really_interrupt_work(manager, operation, state):
    entered = threading.Event()
    class Blocking:
        def fetch(self,url,check):
            entered.set()
            for _ in range(200):
                check()
                time.sleep(.01)
            raise AssertionError("中断未生效")
    manager.downloader = Blocking()
    task = make_task(manager)
    manager.action(task["task_id"], "start")
    assert entered.wait(2)
    manager.action(task["task_id"], operation)
    time.sleep(.1)
    assert manager.get(task["task_id"])["status"] == state
    assert manager.results(task["task_id"])["total"] == 0
    manager.downloader = FixtureDownloader()
    manager.action(task["task_id"], "resume")
    assert wait_for(manager, task["task_id"])["record_count"] == 2


def test_export_formula_safety_precision_and_backup(manager):
    task = make_task(manager)
    manager.action(task["task_id"], "start"); wait_for(manager, task["task_id"])
    exporter = Exporter(manager)
    csv_path = exporter.file(exporter.create(task["task_id"],"csv")["export_id"])
    assert csv_path.read_bytes().startswith(b"\xef\xbb\xbf")
    assert "'=HYPERLINK" in csv_path.read_text(encoding="utf-8-sig")
    assert "1,234.56" in csv_path.read_text(encoding="utf-8-sig")
    xlsx = exporter.file(exporter.create(task["task_id"],"xlsx")["export_id"])
    with zipfile.ZipFile(xlsx) as archive:
        sheet = archive.read("xl/worksheets/sheet1.xml")
        assert b"<f>" not in sheet and b"HYPERLINK" in sheet
        assert len([n for n in archive.namelist() if n.startswith("xl/worksheets/sheet") and n.endswith(".xml")]) == 3
    js = json.loads(exporter.file(exporter.create(task["task_id"],"json")["export_id"]).read_text(encoding="utf-8"))
    assert len(js["records"]) == 2 and js["sources"]
    backup = exporter.file(exporter.backup()["export_id"])
    with sqlite3.connect(backup) as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert db.execute("SELECT count(*) FROM task_records").fetchone()[0] == 2


def test_schedule_next_run_and_restart_recovery(manager):
    task = make_task(manager, interval_seconds=86400)
    manager.action(task["task_id"],"start")
    assert wait_for(manager,task["task_id"])["next_run_at"] is not None
    with manager.store.connect() as db:
        db.execute("UPDATE tasks SET status='running' WHERE task_id=?",(task["task_id"],))
    manager.close()
    reopened = TaskManager(manager.store)
    try:
        assert reopened.get(task["task_id"])["status"] == "paused"
        assert reopened.results(task["task_id"])["total"] == 2
    finally:
        reopened.close()


def test_edit_copy_delete_are_persisted(manager):
    task = make_task(manager)
    copied = manager.action(task["task_id"],"copy")
    assert copied["status"]=="draft" and copied["task_id"]!=task["task_id"]
    manager.update(copied["task_id"],TaskDefinition(name="更新后的任务",urls=copied["urls"],fields=["名称"]))
    assert manager.get(copied["task_id"])["name"]=="更新后的任务"
    manager.action(task["task_id"],"delete")
    assert manager.list()["total"]==1
