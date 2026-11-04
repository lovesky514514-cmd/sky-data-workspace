"""验证隐藏后台进程的真实模型问答，不打印会话令牌。"""

import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from sky_data_workspace.config import MODEL_NAME, PROJECT_ROOT


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    info = json.loads((PROJECT_ROOT / "workspace_data/runtime.json").read_text(encoding="utf-8"))
    address = urlsplit(info["base_url"])
    if address.scheme != "http" or address.hostname != "127.0.0.1" or address.username or address.password:
        raise RuntimeError("运行时地址不符合回环限制")
    with httpx.Client(base_url=info["base_url"], headers={"Authorization": "Bearer " + info["token"]},
                      trust_env=False, timeout=600) as client:
        response = client.post("/api/ai/ask", json={
            "question": "静态HTML页面与JavaScript动态页面应如何选择采集工具？"
        })
        result = response.json()
        report = {"http_status": response.status_code, "result": result, "desktop_used": False}
        passed = (response.status_code == 200 and result.get("model") == MODEL_NAME
                  and bool(result.get("citations")) and bool(result.get("tool_trace"))
                  and all(t["initiated_by"] == "model" for t in result.get("tool_trace", [])))
        report["passed"] = passed
        status = client.get("/api/ai/status").json()
        report["backend_data"] = status["data"]
    output = PROJECT_ROOT / "artifacts/live/deployed_api.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": passed, "http_status": response.status_code,
                      "model": result.get("model"), "elapsed_seconds": result.get("elapsed_seconds")}, ensure_ascii=False))
    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    main()
