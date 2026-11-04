import hmac
import json
import os
import secrets
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

from pydantic import ValidationError

from . import __version__
from .ai_service import AIService
from .evidence import MappingRequest
from .knowledge import LookupArguments
from .ollama_client import AIError
from .tasks import TaskManager, TaskDefinition
from .exporting import Exporter


def create_server(service: AIService, port: int = 0):
    token = secrets.token_hex(32)
    tasks = TaskManager(service.store)
    exporter = Exporter(tasks)

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(10)

        def log_message(self, *_):
            # 不把请求正文、认证令牌或用户数据写入控制台日志。
            pass

        def send_json(self, status: int, data: dict):
            content = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            try:
                self.wfile.write(content)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def authorized(self) -> bool:
            expected_hosts = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
            if self.headers.get("Host") not in expected_hosts:
                self.send_json(403, {"error": "host_not_allowed"})
                return False
            if self.headers.get("Origin") not in {None, "tauri://localhost", "http://tauri.localhost"}:
                self.send_json(403, {"error": "origin_not_allowed"})
                return False
            if not hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + token):
                self.send_json(401, {"error": "authentication_required"})
                return False
            return True

        def do_GET(self):
            if not self.authorized():
                return
            try:
                parsed = urlsplit(self.path)
                query = parse_qs(parsed.query)
                number = lambda name, default: int(query.get(name, [default])[0])
                parts = parsed.path.strip("/").split("/")
                if parsed.path == "/api/health":
                    result = {"product": "SKY Data Workspace", "runtime": "running", "version": __version__}
                elif parsed.path == "/api/ai/status":
                    result = service.status()
                elif parsed.path == "/api/tasks":
                    result = tasks.list(offset=number("offset", 0), limit=number("limit", 20),
                                        q=query.get("q", [""])[0], status=query.get("status", [""])[0])
                elif len(parts) == 4 and parts[:2] == ["api", "tasks"]:
                    if parts[3] == "results":
                        result = tasks.results(parts[2], offset=number("offset", 0), limit=number("limit", 100))
                    elif parts[3] == "logs":
                        result = tasks.logs(parts[2])
                    else:
                        self.send_json(404, {"error": "not_found"})
                        return
                elif len(parts) == 3 and parts[:2] == ["api", "exports"]:
                    path = exporter.file(parts[2])
                    if path.stat().st_size > 128 * 1024 * 1024:
                        raise AIError("export_too_large", "导出文件过大")
                    content = path.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/octet-stream")
                    self.send_header("Content-Length", str(len(content)))
                    self.send_header("Connection", "close")
                    self.send_header("X-Content-Type-Options", "nosniff")
                    self.end_headers()
                    self.wfile.write(content)
                    return
                else:
                    self.send_json(404, {"error": "not_found"})
                    return
                self.send_json(200, result)
            except (ValueError, TypeError):
                self.send_json(400, {"error": "invalid_request"})
            except AIError as error:
                self.send_json(422, {"error": error.code, "message": str(error)})

        def do_POST(self):
            if not self.authorized():
                return
            if self.headers.get_content_type() != "application/json":
                self.send_json(415, {"error": "json_required"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 512 * 1024:
                    # 小幅超限请求有界丢弃，避免 Windows 关闭未读 socket 时重置已发送的 413。
                    if 512 * 1024 < length <= 1024 * 1024:
                        remaining = length
                        while remaining:
                            chunk = self.rfile.read(min(remaining, 65536))
                            if not chunk:
                                break
                            remaining -= len(chunk)
                    self.send_json(413, {"error": "invalid_body_size"})
                    return
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise ValueError("请求必须是对象")
                if self.path == "/api/shutdown":
                    if data:
                        raise ValueError("关闭请求不接收参数")
                    self.send_json(200, {"shutdown": "requested"})
                    threading.Thread(target=self.server.shutdown, daemon=True).start()
                    return
                elif self.path == "/api/knowledge/search":
                    result = service.knowledge.lookup(LookupArguments.model_validate(data))
                elif self.path == "/api/ai/ask":
                    if set(data) != {"question"}:
                        raise ValueError("请求只能包含 question")
                    result = service.ask(data["question"])
                elif self.path == "/api/ai/map-fields":
                    if set(data) - {"evidence", "engine"}:
                        raise ValueError("请求包含未知参数")
                    result = service.map_fields(
                        MappingRequest.model_validate(data.get("evidence")),
                        engine=data.get("engine", "qwen"),
                    )
                elif self.path == "/api/ai/check":
                    result = service.check_inference()
                elif self.path == "/api/settings":
                    result = service.update_settings(data)
                elif self.path == "/api/tasks":
                    result = tasks.create(TaskDefinition.model_validate(data))
                elif self.path == "/api/tasks/update":
                    result = tasks.update(data["task_id"], TaskDefinition.model_validate(data["definition"]))
                elif self.path == "/api/tasks/action":
                    result = tasks.action(data["task_id"], data["action"])
                elif self.path == "/api/tasks/preview":
                    if set(data) != {"url"}:
                        raise ValueError("请求仅允许url")
                    result = tasks.preview(data["url"])
                elif self.path == "/api/tasks/review":
                    result = tasks.review(data["record_id"], data["status"])
                elif self.path == "/api/tasks/export":
                    result = exporter.create(data["task_id"], data["format"])
                elif self.path == "/api/backup":
                    result = exporter.backup()
                else:
                    self.send_json(404, {"error": "not_found"})
                    return
                self.send_json(200, result)
            except AIError as exc:
                code = 504 if exc.code == "model_timeout" else 503 if exc.code in {
                    "ai_busy", "ollama_unavailable", "model_missing", "ai_disabled", "knowledge_unavailable"
                } else 422
                self.send_json(code, {"error": exc.code, "message": str(exc)})
            except (ValueError, TypeError, KeyError, ValidationError):
                self.send_json(400, {"error": "invalid_request"})
            except (socket.timeout, ConnectionError):
                return
            except Exception:
                self.send_json(500, {"error": "internal_error"})

    class RuntimeHTTPServer(ThreadingHTTPServer):
        def server_close(self):
            tasks.close()
            super().server_close()
    server = RuntimeHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = False
    return server, token


def serve(service: AIService, port: int = 0, launch_id: str | None = None, parent_pid: int = 0):
    server, token = create_server(service, port)
    info_path: Path = service.settings.data_dir / "runtime.json"
    info = {"pid": os.getpid(), "base_url": f"http://127.0.0.1:{server.server_port}",
            "token": token, "product": "SKY Data Workspace", "launch_id": launch_id}
    temporary = info_path.with_name(f".runtime-{os.getpid()}.json")
    temporary.write_text(json.dumps(info), encoding="utf-8")
    os.replace(temporary, info_path)
    print(json.dumps({"state": "listening", "base_url": info["base_url"]}), flush=True)
    if parent_pid:
        from .parent_monitor import watch
        threading.Thread(target=watch, args=(parent_pid, server.shutdown), daemon=True, name="sky-parent-monitor").start()
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        service.close()
        # 只清理本进程创建的会话文件。
        if info_path.is_file():
            existing = json.loads(info_path.read_text(encoding="utf-8"))
            if existing.get("pid") == os.getpid():
                info_path.unlink()
