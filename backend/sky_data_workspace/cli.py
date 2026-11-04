import argparse
import json
import sys
from pathlib import Path

from .ai_service import AIService
from .config import Settings
from .evidence import MappingRequest
from .ollama_client import AIError
from .server import serve


def main():
    if sys.stdout is not None and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="SKY Data Workspace 本地 AI 运行时")
    parser.add_argument("--ai-off", action="store_true")
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--timeout", type=float, default=240)
    parser.add_argument("--gpu", action="store_true", help="显式允许自动 GPU 分配；默认 CPU")
    parser.add_argument("--launch-id", help=argparse.SUPPRESS)
    parser.add_argument("--parent-pid", type=int, default=0, help=argparse.SUPPRESS)
    parser.add_argument("--knowledge-db", type=Path, help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    ask = sub.add_parser("ask")
    ask.add_argument("question")
    mapping = sub.add_parser("map-fields")
    mapping.add_argument("evidence_json", type=Path)
    mapping.add_argument("--rules", action="store_true")
    server = sub.add_parser("serve")
    server.add_argument("--port", type=int, default=0)
    args = parser.parse_args()
    config = {"ai_enabled": not args.ai_off, "timeout_seconds": args.timeout,
              "gpu_layers": -1 if args.gpu else 0}
    if args.data_dir:
        config["data_dir"] = args.data_dir.resolve()
    data_dir = config.get("data_dir", Settings().data_dir)
    settings_path = data_dir / "settings.json"
    if settings_path.is_file():
        preferences = json.loads(settings_path.read_text(encoding="utf-8"))
        config.update({k: v for k, v in preferences.items() if k in {"ai_enabled", "cpu_threads", "gpu_layers"}})
    if args.ai_off:
        config["ai_enabled"] = False
    if args.gpu:
        config["gpu_layers"] = -1
    if args.knowledge_db:
        config["knowledge_db"] = args.knowledge_db.resolve()
    service = AIService(Settings(**config))
    try:
        if args.command == "serve":
            serve(service, args.port, args.launch_id, args.parent_pid)
            return
        if args.command == "status":
            result = service.status()
        elif args.command == "ask":
            result = service.ask(args.question)
        else:
            request = MappingRequest.model_validate_json(args.evidence_json.read_text(encoding="utf-8-sig"))
            result = service.map_fields(request, engine="rules" if args.rules else "qwen")
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except AIError as exc:
        print(json.dumps({"error": exc.code, "message": str(exc)}, ensure_ascii=False))
        raise SystemExit(1)
    finally:
        if args.command != "serve":
            service.close()
