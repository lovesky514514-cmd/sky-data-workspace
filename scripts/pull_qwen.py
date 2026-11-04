"""后台下载指定的 9B 模型，保存真实 Ollama 进度，不打开窗口。"""

import http.client
import json
from datetime import datetime, timezone
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1] / "artifacts" / "ollama"
    root.mkdir(parents=True, exist_ok=True)
    connection = http.client.HTTPConnection("127.0.0.1", 11434, timeout=600)
    connection.request("POST", "/api/pull", json.dumps({"model": "qwen3.5:9b", "stream": True}),
                       {"Content-Type": "application/json"})
    response = connection.getresponse()
    if response.status != 200:
        raise RuntimeError(f"Ollama pull HTTP {response.status}: {response.read(8192)!r}")
    previous = None
    success = False
    with (root / "pull.jsonl").open("a", encoding="utf-8") as log:
        for line in response:
            event = json.loads(line)
            event["observed_at"] = datetime.now(timezone.utc).isoformat()
            log.write(json.dumps(event, ensure_ascii=False) + "\n")
            log.flush()
            if event.get("error"):
                raise RuntimeError(event["error"])
            total, completed = event.get("total", 0), event.get("completed", 0)
            percent = int(100 * completed / total) if total else None
            marker = (event.get("status"), percent // 5 if percent is not None else None)
            if marker != previous:
                print(json.dumps({"status": event.get("status"), "percent": percent,
                                  "completed": completed, "total": total}), flush=True)
                previous = marker
            success |= event.get("status") == "success"
    connection.close()
    if not success:
        raise RuntimeError("下载流结束，但 Ollama 未报告 success")


if __name__ == "__main__":
    main()
