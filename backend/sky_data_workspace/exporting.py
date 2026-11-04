import csv
import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone

import xlsxwriter

from .ollama_client import AIError
from .tasks import now


class Exporter:
    def __init__(self, manager):
        self.manager = manager
        self.directory = manager.directory / "exports"
        self.directory.mkdir(exist_ok=True)

    def _register(self, filename, export_id):
        with self.manager.store.connect() as db:
            db.execute("INSERT INTO exports VALUES (?,?,?)", (export_id, filename, now()))
        return {"export_id": export_id, "filename": filename}

    def create(self, task_id, format):
        if format not in {"csv", "xlsx", "json"}:
            raise AIError("invalid_export", "导出格式无效")
        task = self.manager.get(task_id)
        with self.manager.store.connect() as db:
            db.row_factory = sqlite3.Row
            rows = [dict(r) for r in db.execute("SELECT * FROM task_records WHERE task_id=? ORDER BY retrieved_at,record_id", (task_id,))]
            sources = [dict(r) for r in db.execute("SELECT * FROM task_sources WHERE task_id=?", (task_id,))]
        if not rows:
            raise AIError("no_records", "该任务还没有可导出的结果")
        for row in rows:
            row["data"] = json.loads(row.pop("data_json"))
        fields = list(dict.fromkeys(key for row in rows for key in row["data"]))
        metadata = ["source_url", "retrieved_at", "content_hash", "evidence_locator", "review_status"]
        export_id = uuid.uuid4().hex
        title = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", task["name"])[:60]
        filename = f"SKY_{title}_{datetime.now(timezone.utc):%Y%m%d_%H%M%S}_{export_id[:6]}.{format}"
        path = self.directory / filename
        if format == "json":
            path.write_text(json.dumps({"task": task, "records": rows, "sources": sources},
                                       ensure_ascii=False, indent=2), encoding="utf-8")
        elif format == "csv":
            def safe(value):
                value = "" if value is None else str(value)
                return "'" + value if value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")) else value
            with path.open("w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(fields + metadata)
                for row in rows:
                    writer.writerow([safe(row["data"].get(f)) for f in fields] + [safe(row[m]) for m in metadata])
        else:
            with xlsxwriter.Workbook(path, {"constant_memory": True, "strings_to_formulas": False, "strings_to_urls": False}) as book:
                header = book.add_format({"bold": True, "bg_color": "#EAF0FF", "font_color": "#254A8A", "border": 1})
                def sheet(name, columns, values):
                    ws = book.add_worksheet(name)
                    ws.freeze_panes(1, 0)
                    ws.set_column(0, len(columns)-1, 23)
                    for c, value in enumerate(columns):
                        ws.write_string(0, c, value, header)
                    for r, values_row in enumerate(values, 1):
                        for c, value in enumerate(values_row):
                            if value is None:
                                ws.write_blank(r, c, None)
                            else:
                                ws.write_string(r, c, str(value)[:32767])
                    ws.autofilter(0, 0, max(1, len(values)), len(columns)-1)
                sheet("采集数据", fields + metadata, [
                    [row["data"].get(f) for f in fields] + [row[m] for m in metadata] for row in rows])
                sheet("来源信息", ["source_url", "state", "content_hash", "error"],
                      [[source.get(c) for c in ["source_url", "state", "content_hash", "error"]] for source in sources])
                sheet("质量与审核", ["record_id", "review_status", "说明"],
                      [[row["record_id"], row["review_status"], "原始来源已保存；尚未进行完整业务语义校验"] for row in rows])
        return self._register(filename, export_id)

    def backup(self):
        export_id = uuid.uuid4().hex
        filename = f"SKY_database_{datetime.now(timezone.utc):%Y%m%d_%H%M%S}_{export_id[:6]}.sqlite3"
        with self.manager.store.connect() as source:
            target = sqlite3.connect(self.directory / filename)
            try:
                source.backup(target)
            finally:
                target.close()
        return self._register(filename, export_id)

    def file(self, export_id):
        if not re.fullmatch(r"[a-f0-9]{32}", export_id):
            raise AIError("export_missing", "导出文件不存在")
        with self.manager.store.connect() as db:
            row = db.execute("SELECT filename FROM exports WHERE export_id=?", (export_id,)).fetchone()
        if not row:
            raise AIError("export_missing", "导出文件不存在")
        path = self.directory / row[0]
        if path.resolve().parent != self.directory.resolve():
            raise AIError("export_missing", "导出路径不安全")
        if not path.is_file():
            raise AIError("export_missing", "导出文件已经移动或删除")
        return path
