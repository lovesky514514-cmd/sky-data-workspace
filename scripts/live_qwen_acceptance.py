"""后台真实模型验收：不打开界面，不抓取桌面，不下载其他模型。"""

from __future__ import annotations

import base64
import hashlib
import importlib.metadata
import json
import struct
import sys
import threading
import time
import zlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import httpx
from pydantic import Field

from sky_data_workspace.ai_service import AIService
from sky_data_workspace.config import MODEL_NAME, PROJECT_ROOT, Settings
from sky_data_workspace.evidence import MappingRequest, StrictModel
from sky_data_workspace.ollama_client import metrics, parse_structured
from sky_data_workspace.server import create_server

OUT = PROJECT_ROOT / "artifacts" / "live"


class Ready(StrictModel):
    ready: bool
    model: Literal["qwen3.5:9b"]


class Color(StrictModel):
    color: Literal["red", "green", "blue", "white"]


def red_png() -> bytes:
    """已知像素的合成红色测试图，不是截图或真实文档。"""
    width, height = 128, 96
    def chunk(name, data):
        return struct.pack(">I", len(data)) + name + data + struct.pack(">I", zlib.crc32(name + data) & 0xffffffff)
    scanlines = (b"\0" + bytes((255, 0, 0)) * width) * height
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(scanlines)) + chunk(b"IEND", b""))


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    OUT.mkdir(parents=True, exist_ok=True)
    report = {
        "started_at": datetime.now(timezone.utc).isoformat(), "model": MODEL_NAME,
        "desktop_used": False, "cpu_threads": 4, "gpu_layers": 0,
        "cases": [], "limitations": ["合成表格与单色图只验证接入链路，不代表真实财报/OCR准确率", "未完成桌面及安装验收"],
    }
    report["source_sha256"] = {
        p.relative_to(PROJECT_ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted((PROJECT_ROOT / "backend/sky_data_workspace").glob("*.py"))
    }
    report["knowledge_sha256"] = hashlib.sha256(settings_path.read_bytes()).hexdigest() if (
        settings_path := PROJECT_ROOT / "research/knowledge.sqlite3"
    ).is_file() else None
    settings = Settings(data_dir=OUT / "runtime_data")
    service = AIService(settings)

    def save():
        (OUT / "acceptance.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    def case(name, action):
        started = time.perf_counter()
        try:
            result = action()
            entry = {"name": name, "passed": True, "result": result}
        except Exception as exc:
            entry = {"name": name, "passed": False, "error_type": type(exc).__name__, "error": str(exc)}
        entry["elapsed_seconds"] = round(time.perf_counter() - started, 3)
        report["cases"].append(entry)
        save()
        print(json.dumps({k: entry[k] for k in ("name", "passed", "elapsed_seconds")}, ensure_ascii=False), flush=True)
        return entry["passed"]

    def status():
        result = service.status()
        assert result["ai"]["connected"] and result["ai"]["installed"], result
        assert result["ai"]["model"] == MODEL_NAME
        return result

    def structured():
        response = service.client.chat([
            {"role": "user", "content": 'Return JSON with ready=true and model="qwen3.5:9b".'}
        ], schema=Ready.model_json_schema(), predict_tokens=96)
        result = parse_structured(response, Ready)
        assert result.ready and result.model == MODEL_NAME
        return {"output": result.model_dump(), "metrics": metrics(response)}

    def text():
        response = service.client.chat([{"role": "user", "content": "只回复 SKY_READY，不要输出其他内容。"}], predict_tokens=32)
        assert response["message"]["content"].strip() == "SKY_READY", response["message"]["content"]
        return {"output": response["message"]["content"], "metrics": metrics(response)}

    def vision():
        png = red_png()
        (OUT / "vision_red.png").write_bytes(png)
        response = service.client.chat([{"role": "user", "content": "What is the dominant color in this image? Return the color enum.",
                                         "images": [base64.b64encode(png).decode()]}],
                                       schema=Color.model_json_schema(), predict_tokens=64)
        result = parse_structured(response, Color)
        assert result.color == "red"
        return {"output": result.model_dump(), "fixture_sha256": hashlib.sha256(png).hexdigest(),
                "fixture_kind": "synthetic_known_pixels", "metrics": metrics(response)}

    def tool_qa():
        result = service.ask("扫描版PDF应该怎么提取数据并核验数字？")
        assert result["tool_trace"] and all(t["initiated_by"] == "model" for t in result["tool_trace"])
        assert result["citations"] and result["sources"]
        return result

    def mapping():
        request = MappingRequest.model_validate_json(
            (PROJECT_ROOT / "backend/tests/fixtures/financial_table.json").read_text(encoding="utf-8"))
        result = service.map_fields(request)
        actual = {r["field_name"]: r for r in result["records"]}
        assert actual["revenue"]["value"] == "12345600.00"
        assert actual["profit"]["value"] == "-1234500.00"
        assert actual["assets"]["value"] is None and actual["assets"]["validation_status"] == "missing"
        assert all(r["review_status"] == "pending" for r in result["records"])
        result["fixture_kind"] = "synthetic_manually_labelled"
        return result

    def missing():
        result = service.ask("请给出某未指定公司2025年的营业收入金额，目前没有任何原始报表或网页。")
        assert result["missing"] is True
        return result

    def api():
        server, token = create_server(service)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{server.server_port}",
                              headers={"Authorization": "Bearer " + token}, trust_env=False, timeout=600) as client:
                response = client.post("/api/ai/ask", json={"question": "采集网页时什么时候使用HTTPX，什么时候使用Playwright？"})
                assert response.status_code == 200, response.text[:500]
                result = response.json()
                assert result["model"] == MODEL_NAME and result["tool_trace"] and result["citations"]
                return {"http_status": response.status_code, "result": result}
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=10)

    try:
        if case("service_and_exact_model", status):
            case("real_text_inference", text)
            case("real_json_schema", structured)
            case("real_vision_known_color", vision)
            case("model_initiated_knowledge_tool", tool_qa)
            case("evidence_mapping_decimal_units_and_missing", mapping)
            case("no_source_amount_abstention", missing)
            case("application_api_to_model_and_knowledge", api)
            report["loaded_models"] = service.client.request("GET", "/api/ps")
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        report["passed"] = all(c["passed"] for c in report["cases"]) and len(report["cases"]) == 8
        report["installed_packages"] = {p: importlib.metadata.version(p) for p in ("httpx", "pydantic", "jsonschema")}
        save()
    finally:
        service.close()
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
