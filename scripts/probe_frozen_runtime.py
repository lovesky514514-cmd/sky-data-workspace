"""在后台验证冻结运行时、真实公开来源、导出、中文路径及退出。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid
import zipfile

import httpx

ROOT = Path(__file__).resolve().parents[1]


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, default=ROOT/"artifacts/frozen/sky-data-runtime.exe")
    parser.add_argument("--data-dir", type=Path, default=ROOT/"artifacts/desktop-check/中文用户 路径")
    parser.add_argument("--report", type=Path, default=ROOT/"artifacts/desktop-check/frozen-report.json")
    parser.add_argument("--leave-running", action="store_true")
    args = parser.parse_args()
    directory = args.data_dir.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    nonce = uuid.uuid4().hex
    log = (directory/"runtime.log").open("w",encoding="utf-8")
    process = subprocess.Popen([str(args.binary.resolve()),"--data-dir",str(directory),"--launch-id",nonce,"serve"],
                               stdout=log,stderr=log,stdin=subprocess.DEVNULL,
                               creationflags=subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0)
    started=time.monotonic()
    info_path=directory/"runtime.json"
    info=None
    while time.monotonic()-started<45:
        if process.poll() is not None: raise RuntimeError("Frozen runtime exited; inspect runtime.log")
        if info_path.is_file():
            try:
                value=json.loads(info_path.read_text(encoding="utf-8"))
                if value.get("launch_id")==nonce: info=value;break
            except ValueError: pass
        time.sleep(.1)
    if not info: raise RuntimeError("Frozen runtime startup timeout")
    report={"runtime_started":True,"desktop_used":False,"unicode_space_path":True,
            "binary_sha256":hashlib.sha256(args.binary.read_bytes()).hexdigest(),"cases":[]}
    client=httpx.Client(base_url=info["base_url"],headers={"Authorization":"Bearer "+info["token"]},trust_env=False,timeout=120)
    def request(path, body=None):
        response=client.get(path) if body is None else client.post(path,json=body)
        response.raise_for_status()
        return response.json()
    try:
        report["health"]=request("/api/health")
        report["ai"]=request("/api/ai/status")
        report["knowledge"]=request("/api/knowledge/search",{"query":"PDF OCR"})
        sources=[("Python 发布版本","https://www.python.org/downloads/"),
                 ("Ollama 仓库信息","https://api.github.com/repos/ollama/ollama")]
        for name,url in sources:
            task=request("/api/tasks",{"name":name,"urls":[url],"fields":[],"interval_seconds":None})
            task_id=task["task_id"]
            request("/api/tasks/action",{"task_id":task_id,"action":"start"})
            deadline=time.monotonic()+100
            while time.monotonic()<deadline:
                values=request("/api/tasks?limit=100")["tasks"]
                task=next(t for t in values if t["task_id"]==task_id)
                if task["status"] in {"completed","partial","failed"}:break
                time.sleep(.4)
            assert task["status"]=="completed" and task["record_count"]>0,request(f"/api/tasks/{task_id}/logs")
            rows=request(f"/api/tasks/{task_id}/results")
            assert rows["records"] and all(r["content_hash"] for r in rows["records"])
            files=[]
            for format in ("xlsx","csv","json"):
                meta=request("/api/tasks/export",{"task_id":task_id,"format":format})
                response=client.get("/api/exports/"+meta["export_id"]);response.raise_for_status()
                path=directory/meta["filename"];path.write_bytes(response.content)
                if format=="xlsx":
                    with zipfile.ZipFile(path) as archive:assert "xl/workbook.xml" in archive.namelist()
                elif format=="json":assert json.loads(response.content)["records"]
                elif format=="csv":assert response.content.startswith(b"\xef\xbb\xbf")
                files.append({"format":format,"bytes":len(response.content)})
            report["cases"].append({"source_url":url,"task":task,"exports":files})
            print(json.dumps({"source":url,"records":task["record_count"],"exports":"xlsx/csv/json passed"}),flush=True)
        backup=request("/api/backup",{})
        assert client.get("/api/exports/"+backup["export_id"]).content.startswith(b"SQLite format 3")
        report["backup_passed"]=True
        if args.leave_running:
            report["left_running"]=True
        else:
            request("/api/shutdown",{})
            process.wait(timeout=20)
            report["runtime_stopped"]=process.returncode==0
        report["passed"]=True
    except Exception as error:
        report["passed"]=False;report["error"]=str(error)
        raise
    finally:
        if not args.leave_running:
            if process.poll() is None:
                try:request("/api/shutdown",{});process.wait(timeout=20)
                except Exception:process.terminate();process.wait(timeout=10)
        client.close();log.close()
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")


if __name__=="__main__":main()
