import hashlib
import json
import queue
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone

from pydantic import Field, field_validator

from .evidence import StrictModel
from .extraction import extract
from .fetching import SafeDownloader, normalize_url
from .ollama_client import AIError
from .storage import RuntimeStore


def now():
    return datetime.now(timezone.utc).isoformat()


class TaskDefinition(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    urls: list[str] = Field(min_length=1, max_length=30)
    fields: list[str] = Field(default_factory=list, max_length=100)
    interval_seconds: int | None = Field(default=None, ge=900, le=31536000)

    @field_validator("name")
    @classmethod
    def name_valid(cls, value):
        if not value.strip():
            raise ValueError("任务名称不能为空")
        return value.strip()

    @field_validator("urls")
    @classmethod
    def urls_valid(cls, values):
        return list(dict.fromkeys(normalize_url(v) for v in values))

    @field_validator("fields")
    @classmethod
    def fields_valid(cls, values):
        if any(not value or len(value) > 120 for value in values):
            raise ValueError("字段名称无效")
        return list(dict.fromkeys(values))


class Interrupted(Exception):
    pass


class TaskManager:
    def __init__(self, store: RuntimeStore):
        self.store = store
        self.directory = store.path.parent
        self.downloader = SafeDownloader()
        self.queue = queue.Queue()
        self.events: dict[str, threading.Event] = {}
        self.lock = threading.RLock()
        self.stopping = threading.Event()
        with store.connect() as db:
            db.execute("UPDATE tasks SET status='paused' WHERE status IN ('running','queued')")
            db.execute("UPDATE task_sources SET state='pending' WHERE state='running'")
        self.worker = threading.Thread(target=self._work, name="sky-collector", daemon=True)
        self.scheduler = threading.Thread(target=self._schedule, name="sky-scheduler", daemon=True)
        self.worker.start()
        self.scheduler.start()

    def close(self):
        self.stopping.set()
        with self.lock:
            for event in self.events.values():
                event.set()
        self.queue.put(None)
        self.worker.join(timeout=15)
        self.scheduler.join(timeout=2)

    def log(self, task_id, level, message, db=None):
        if db is None:
            with self.store.connect() as connection:
                self.log(task_id, level, message, connection)
        else:
            db.execute("INSERT INTO task_logs(task_id,created_at,level,message) VALUES (?,?,?,?)",
                       (task_id, now(), level, message))

    def create(self, definition: TaskDefinition):
        task_id = str(uuid.uuid4())
        stamp = now()
        with self.store.connect() as db:
            db.execute("INSERT INTO tasks(task_id,name,urls_json,fields_json,status,created_at,updated_at,interval_seconds) "
                       "VALUES (?,?,?,?,?,?,?,?)", (task_id, definition.name.strip(), json.dumps(definition.urls),
                       json.dumps(definition.fields, ensure_ascii=False), "draft", stamp, stamp, definition.interval_seconds))
            db.executemany("INSERT INTO task_sources(task_id,source_url) VALUES (?,?)",
                           [(task_id, url) for url in definition.urls])
            self.log(task_id, "info", "任务已创建，尚未执行。", db)
        return self.get(task_id)

    def get(self, task_id):
        with self.store.connect() as db:
            db.row_factory = sqlite3.Row
            row = db.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
            if row is None:
                raise AIError("task_missing", "任务不存在")
            task = dict(row)
            task["urls"] = json.loads(task.pop("urls_json"))
            task["fields"] = json.loads(task.pop("fields_json"))
            sources = db.execute("SELECT state,count(*) FROM task_sources WHERE task_id=? GROUP BY state", (task_id,)).fetchall()
            counts = {r[0]: r[1] for r in sources}
            task.update(total=len(task["urls"]), completed=counts.get("done", 0), failed=counts.get("failed", 0),
                        record_count=db.execute("SELECT count(*) FROM task_records WHERE task_id=?", (task_id,)).fetchone()[0])
            task["progress"] = round(100 * (task["completed"] + task["failed"]) / max(1, task["total"]))
            return task

    def list(self, *, offset=0, limit=20, q="", status=""):
        where, args = "1=1", []
        if q:
            where += " AND name LIKE ?"
            args.append("%" + q[:200] + "%")
        if status:
            where += " AND status=?"
            args.append(status)
        with self.store.connect() as db:
            total = db.execute(f"SELECT count(*) FROM tasks WHERE {where}", args).fetchone()[0]
            ids = db.execute(f"SELECT task_id FROM tasks WHERE {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
                             [*args, min(100, max(1, limit)), max(0, offset)]).fetchall()
            counts = dict(db.execute("SELECT status,count(*) FROM tasks GROUP BY status").fetchall())
            records = db.execute("SELECT count(*) FROM task_records").fetchone()[0]
        return {"tasks": [self.get(row[0]) for row in ids], "total": total, "counts": counts, "records": records}

    def update(self, task_id, definition):
        with self.lock:
            task = self.get(task_id)
            if task["status"] in {"running", "queued"}:
                raise AIError("task_busy", "请先暂停任务再编辑")
            with self.store.connect() as db:
                db.execute("UPDATE tasks SET name=?,urls_json=?,fields_json=?,interval_seconds=?,status='draft',"
                           "updated_at=?,next_run_at=NULL,generation=generation+1 WHERE task_id=?",
                           (definition.name, json.dumps(definition.urls), json.dumps(definition.fields, ensure_ascii=False),
                            definition.interval_seconds, now(), task_id))
                db.execute("DELETE FROM task_sources WHERE task_id=?", (task_id,))
                db.executemany("INSERT INTO task_sources(task_id,source_url) VALUES (?,?)",
                               [(task_id, url) for url in definition.urls])
                self.log(task_id, "info", "任务配置已更新，历史数据仍保留。", db)
            return self.get(task_id)

    def action(self, task_id, action):
        with self.lock:
            task = self.get(task_id)
            if action == "copy":
                return self.create(TaskDefinition(name=task["name"][:110] + "（副本）", urls=task["urls"],
                                                  fields=task["fields"], interval_seconds=task["interval_seconds"]))
            if action in {"delete", "pause", "cancel"}:
                if action == "delete" and task["status"] in {"running", "queued"}:
                    raise AIError("task_busy", "请先暂停或取消任务，再删除")
                self.events.setdefault(task_id, threading.Event()).set()
                with self.store.connect() as db:
                    if action == "delete":
                        db.execute("DELETE FROM tasks WHERE task_id=?", (task_id,))
                        return {"deleted": True}
                    state = "paused" if action == "pause" else "cancelled"
                    db.execute("UPDATE tasks SET status=?,updated_at=?,next_run_at=NULL WHERE task_id=?", (state, now(), task_id))
                    self.log(task_id, "info", "已请求暂停，停止后续调度。" if action == "pause" else "已请求取消并清理当前步骤。", db)
                return self.get(task_id)
            if action not in {"start", "resume", "rerun"}:
                raise AIError("invalid_action", "任务操作无效")
            if task["status"] in {"running", "queued"}:
                return task
            generation = task["generation"] + 1
            with self.store.connect() as db:
                reset = action == "rerun" or task["status"] == "completed"
                if reset:
                    db.execute("UPDATE task_sources SET state='pending',error=NULL WHERE task_id=?", (task_id,))
                else:
                    db.execute("UPDATE task_sources SET state='pending',error=NULL WHERE task_id=? AND state!='done'", (task_id,))
                db.execute("UPDATE tasks SET status='queued',generation=?,updated_at=?,next_run_at=NULL WHERE task_id=?",
                           (generation, now(), task_id))
                self.log(task_id, "info", "任务已进入采集队列。", db)
            event = threading.Event()
            self.events[task_id] = event
            self.queue.put((task_id, generation, event))
            return self.get(task_id)

    def preview(self, url):
        result = self.downloader.fetch(normalize_url(url))
        parsed = extract(result["content"], result["content_type"], result["url"])
        return {**parsed, "rows": parsed["rows"][:5], "total_rows": len(parsed["rows"]), "source_url": result["url"]}

    def _work(self):
        while not self.stopping.is_set():
            item = self.queue.get()
            if item is None:
                break
            task_id, generation, event = item
            try:
                self._run(task_id, generation, event)
            except Interrupted:
                pass
            except Exception:
                try:
                    with self.store.connect() as db:
                        db.execute("UPDATE tasks SET status='failed',updated_at=? WHERE task_id=? AND generation=? AND status='running'",
                                   (now(), task_id, generation))
                    self.log(task_id, "error", "任务执行失败，请检查来源及配置后重试。")
                except Exception:
                    pass

    def _run(self, task_id, generation, event):
        def check():
            if self.stopping.is_set() or event.is_set():
                raise Interrupted()
        check()
        with self.store.connect() as db:
            changed = db.execute("UPDATE tasks SET status='running',last_run_at=?,updated_at=? "
                                 "WHERE task_id=? AND generation=? AND status='queued'", (now(), now(), task_id, generation)).rowcount
            if not changed:
                return
        task = self.get(task_id)
        self.log(task_id, "info", "开始采集；将遵守 robots、限速和公开网络访问限制。")
        for index, url in enumerate(task["urls"]):
            check()
            with self.store.connect() as db:
                state = db.execute("SELECT state FROM task_sources WHERE task_id=? AND source_url=?", (task_id, url)).fetchone()
            if state is None or state[0] == "done":
                continue
            try:
                self.log(task_id, "info", f"正在处理来源 {index+1}/{task['total']}。")
                result = self.downloader.fetch(url, check)
                parsed = extract(result["content"], result["content_type"], result["url"])
                check()
                digest = hashlib.sha256(result["content"]).hexdigest()
                directory = self.directory / "evidence"
                directory.mkdir(exist_ok=True)
                raw = directory / (digest + ".bin")
                if not raw.exists():
                    raw.write_bytes(result["content"])
                fields = task["fields"]
                matching_rows = [row for row in parsed["rows"]
                                 if not fields or any(field in row["data"] for field in fields)]
                if fields and not matching_rows:
                    raise AIError("no_matching_fields", "来源中没有与所选字段匹配的记录")
                stamp = now()
                with self.lock, self.store.connect() as db:
                    current = db.execute("SELECT status,generation FROM tasks WHERE task_id=?", (task_id,)).fetchone()
                    check()
                    if current != ("running", generation):
                        raise Interrupted()
                    for row in matching_rows:
                        data = {field: row["data"].get(field) for field in fields} if fields else row["data"]
                        identity = json.dumps([task_id, result["url"], digest, row["locator"], fields], ensure_ascii=False)
                        record_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()
                        db.execute("INSERT OR IGNORE INTO task_records VALUES (?,?,?,?,?,?,?,?,?)",
                                   (record_id, task_id, result["url"], stamp, digest, row["locator"],
                                    "evidence/" + digest + ".bin", json.dumps(data, ensure_ascii=False), "pending"))
                    db.execute("UPDATE task_sources SET state='done',content_hash=?,warnings_json=? WHERE task_id=? AND source_url=?",
                               (digest, json.dumps(parsed["warnings"], ensure_ascii=False), task_id, url))
                    self.log(task_id, "info", f"来源 {index+1} 已保存 {len(matching_rows)} 行，原始证据已保留。", db)
                    for warning in parsed["warnings"]:
                        self.log(task_id, "warning", warning, db)
            except Interrupted:
                raise
            except Exception as error:
                check()
                message = str(error) if isinstance(error, AIError) else "来源解析失败，内容格式可能不受支持或已损坏"
                with self.lock, self.store.connect() as db:
                    current = db.execute("SELECT status,generation FROM tasks WHERE task_id=?", (task_id,)).fetchone()
                    if current != ("running", generation):
                        raise Interrupted()
                    db.execute("UPDATE task_sources SET state='failed',error=? WHERE task_id=? AND source_url=?", (message, task_id, url))
                    self.log(task_id, "error", f"来源 {index+1}：{message}", db)
        check()
        finished = self.get(task_id)
        status = "completed" if not finished["failed"] else "partial" if finished["completed"] else "failed"
        due = (datetime.now(timezone.utc) + timedelta(seconds=task["interval_seconds"])).isoformat() if task["interval_seconds"] else None
        with self.lock, self.store.connect() as db:
            check()
            db.execute("UPDATE tasks SET status=?,updated_at=?,next_run_at=? WHERE task_id=? AND generation=? AND status='running'",
                       (status, now(), due, task_id, generation))
            self.log(task_id, "info", "本次采集已结束。", db)

    def _schedule(self):
        while not self.stopping.wait(3):
            with self.store.connect() as db:
                ids = db.execute("SELECT task_id FROM tasks WHERE next_run_at<=? AND status IN ('completed','partial','failed')", (now(),)).fetchall()
            for row in ids:
                try:
                    self.action(row[0], "rerun")
                except AIError:
                    pass

    def results(self, task_id, *, offset=0, limit=100):
        self.get(task_id)
        with self.store.connect() as db:
            db.row_factory = sqlite3.Row
            total = db.execute("SELECT count(*) FROM task_records WHERE task_id=?", (task_id,)).fetchone()[0]
            rows = db.execute("SELECT * FROM task_records WHERE task_id=? ORDER BY retrieved_at,record_id LIMIT ? OFFSET ?",
                              (task_id, min(500, max(1, limit)), max(0, offset))).fetchall()
            result = []
            for row in rows:
                value = dict(row)
                value["data"] = json.loads(value.pop("data_json"))
                result.append(value)
        return {"records": result, "total": total}

    def logs(self, task_id):
        self.get(task_id)
        with self.store.connect() as db:
            db.row_factory = sqlite3.Row
            return {"logs": [dict(r) for r in db.execute("SELECT * FROM task_logs WHERE task_id=? ORDER BY log_id DESC LIMIT 300", (task_id,))]}

    def review(self, record_id, status):
        if status not in {"approved", "rejected", "pending"}:
            raise AIError("invalid_review", "审核状态无效")
        with self.store.connect() as db:
            changed = db.execute("UPDATE task_records SET review_status=? WHERE record_id=?", (status, record_id)).rowcount
        if not changed:
            raise AIError("record_missing", "记录不存在")
        return {"updated": True}
