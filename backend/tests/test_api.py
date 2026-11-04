import threading

import httpx

from sky_data_workspace.ai_service import AIService
from sky_data_workspace.config import Settings
from sky_data_workspace.server import create_server


def test_real_loopback_api_auth_origin_validation_and_ai_off(tmp_path):
    """真实回环 HTTP；不启动 UI，不调用模型。"""
    service = AIService(Settings(ai_enabled=False, data_dir=tmp_path))
    server, token = create_server(service)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}"
    try:
        with httpx.Client(base_url=url, trust_env=False, timeout=5) as client:
            assert client.get("/api/health").status_code == 401
            client.headers["Authorization"] = "Bearer " + token
            assert client.get("/api/health").json()["runtime"] == "running"
            assert client.get("/api/health", headers={"Origin": "https://attacker.invalid"}).status_code == 403
            assert client.get("/api/health", headers={"Host": "attacker.invalid"}).status_code == 403
            assert client.post("/api/ai/ask", json={"question": "PDF"}).status_code == 503
            assert client.post("/api/knowledge/search", json={"query": "PDF OCR"}).status_code == 200
            assert client.post("/api/knowledge/search", json={"query": "x", "scope": "developer"}).status_code == 400
            assert client.post("/api/ai/ask", json={"question": "x", "command": "run"}).status_code == 400
            assert client.post("/api/ai/ask", content="hello").status_code == 415
            assert client.post("/api/ai/ask", content=b"x" * (512 * 1024 + 1),
                               headers={"Content-Type": "application/json"}).status_code == 413
            assert client.post("/api/shutdown", json={}).json()["shutdown"] == "requested"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        service.close()
    assert not thread.is_alive()
