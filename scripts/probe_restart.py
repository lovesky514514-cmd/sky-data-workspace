"""Restart only the isolated release-test service and verify its persisted state."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import uuid
import httpx

ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ROOT/'artifacts/release-check/中文用户 路径'
BINARY = ROOT/'artifacts/frozen/sky-data-runtime.exe'


def client_for(info):
    return httpx.Client(base_url=info['base_url'], headers={'Authorization':'Bearer '+info['token']},
                        trust_env=False,timeout=30)


def request(client,path,body=None):
    response=client.get(path) if body is None else client.post(path,json=body)
    response.raise_for_status()
    return response.json()


def snapshot(client):
    tasks=request(client,'/api/tasks?limit=100')['tasks']
    values={}
    for task in tasks:
        rows=request(client,'/api/tasks/'+task['task_id']+'/results')['records']
        values[task['task_id']]={'name':task['name'],'status':task['status'],
            'records':[{k:row[k] for k in ('record_id','content_hash','data','review_status')} for row in rows]}
    return values


def main():
    old_info=json.loads((DIRECTORY/'runtime.json').read_text(encoding='utf-8'))
    with client_for(old_info) as client:
        before=snapshot(client)
        assert len(before)==2 and all(v['records'] for v in before.values())
        original=request(client,'/api/ai/status')['preferences']
        request(client,'/api/settings',{'cpu_threads':2})
        request(client,'/api/shutdown',{})
        for _ in range(100):
            try:
                client.get('/api/health')
                time.sleep(.1)
            except httpx.TransportError:
                break
        else: raise RuntimeError('Old isolated service did not stop')
    nonce=uuid.uuid4().hex
    with (DIRECTORY/'restart.log').open('w',encoding='utf-8') as log:
        process=subprocess.Popen([str(BINARY),'--data-dir',str(DIRECTORY),'--launch-id',nonce,
                                  '--parent-pid',str(os.getpid()),'serve'],
                                 stdin=subprocess.DEVNULL,stdout=log,stderr=log,
                                 creationflags=subprocess.CREATE_NO_WINDOW)
        client=None
        try:
            deadline=time.monotonic()+45
            while time.monotonic()<deadline:
                assert process.poll() is None,'Restart exited early'
                try:
                    info=json.loads((DIRECTORY/'runtime.json').read_text(encoding='utf-8'))
                    if info.get('launch_id')==nonce:
                        client=client_for(info)
                        break
                except (FileNotFoundError,ValueError):
                    pass
                time.sleep(.1)
            assert client,'Restart timed out'
            after=snapshot(client)
            assert before==after,'Task/result/evidence/review state changed on restart'
            assert request(client,'/api/ai/status')['preferences']['cpu_threads']==2
            request(client,'/api/settings',original)
            request(client,'/api/shutdown',{})
            process.wait(timeout=25)
            assert process.returncode==0
            report={'passed':True,'desktop_used':False,'tasks':len(after),
                    'result_rows':sum(len(v['records']) for v in after.values()),
                    'tasks_results_review_evidence_preserved':True,'preferences_preserved':True,
                    'own_runtime_stopped':True,'runtime_sha256':hashlib.sha256(BINARY.read_bytes()).hexdigest()}
            (ROOT/'artifacts/release-check/restart.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
            print(json.dumps(report))
        finally:
            if process.poll() is None:
                if client:
                    try:request(client,'/api/shutdown',{});process.wait(timeout=25)
                    except Exception:pass
                if process.poll() is None:process.terminate();process.wait(timeout=10)
            if client:client.close()


if __name__=='__main__':main()
