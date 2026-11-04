import json
from typing import Any

import httpx
from jsonschema import Draft202012Validator
from pydantic import BaseModel

from .config import MODEL_NAME, Settings


class AIError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.attempt_metrics: list[dict] = []


class OllamaClient:
    def __init__(self, settings: Settings, *, transport: httpx.BaseTransport | None = None):
        self.settings = settings
        self.http = httpx.Client(
            base_url=settings.ollama_url, trust_env=False, follow_redirects=False,
            timeout=httpx.Timeout(settings.timeout_seconds, connect=5),
            limits=httpx.Limits(max_connections=2, max_keepalive_connections=1),
            transport=transport,
        )

    def close(self) -> None:
        self.http.close()

    def request(self, method: str, path: str, payload: dict | None = None) -> dict:
        try:
            with self.http.stream(method, path, json=payload) as response:
                data = bytearray()
                for chunk in response.iter_bytes():
                    data.extend(chunk)
                    if len(data) > 2 * 1024 * 1024:
                        raise AIError("response_too_large", "模型返回超过允许大小")
                if response.status_code >= 300:
                    code = "model_missing" if response.status_code == 404 else "ollama_http_error"
                    raise AIError(code, f"Ollama 返回 HTTP {response.status_code}")
                result = json.loads(data)
        except httpx.TimeoutException as exc:
            raise AIError("model_timeout", "模型调用超时，请稍后重试") from exc
        except httpx.HTTPError as exc:
            raise AIError("ollama_unavailable", "无法连接本机 Ollama 服务") from exc
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise AIError("invalid_json", "Ollama 返回了无效 JSON") from exc
        if not isinstance(result, dict) or result.get("error"):
            raise AIError("ollama_protocol_error", "Ollama 返回无效或失败响应")
        return result

    def status(self) -> dict:
        if not self.settings.ai_enabled:
            return {"enabled": False, "connected": False, "model": MODEL_NAME,
                    "installed": None, "inference_verified": False, "state": "disabled"}
        try:
            version = self.request("GET", "/api/version").get("version")
            models = self.request("GET", "/api/tags").get("models", [])
            match = next((m for m in models if m.get("name") == MODEL_NAME), None)
            details = self.request("POST", "/api/show", {"model": MODEL_NAME}) if match else {}
            return {"enabled": True, "connected": True, "server_version": version,
                    "model": MODEL_NAME, "installed": match is not None,
                    "digest": match.get("digest") if match else None,
                    "size_bytes": match.get("size") if match else None,
                    "details": details.get("details", {}), "capabilities": details.get("capabilities", []),
                    "inference_verified": False, "state": "installed" if match else "model_missing"}
        except AIError as exc:
            return {"enabled": True, "connected": False, "model": MODEL_NAME, "installed": None,
                    "inference_verified": False, "state": exc.code, "error": str(exc)}

    def chat(self, messages: list[dict], *, tools: list[dict] | None = None,
             schema: dict | None = None, predict_tokens: int | None = None) -> dict:
        if not self.settings.ai_enabled:
            raise AIError("ai_disabled", "AI 已关闭，离线知识检索和规则校验仍可使用")
        payload: dict[str, Any] = {
            "model": MODEL_NAME, "messages": messages, "stream": False, "think": False,
            "keep_alive": "2m",
            "options": {"temperature": 0, "num_ctx": self.settings.context_tokens,
                        "num_predict": predict_tokens or self.settings.predict_tokens,
                        "num_thread": self.settings.cpu_threads, "num_gpu": self.settings.gpu_layers},
        }
        if tools:
            payload["tools"] = tools
        if schema:
            Draft202012Validator.check_schema(schema)
            payload["format"] = schema
            # 不依赖服务端约束就能使模型理解字段；宿主校验仍不可省略。
            instruction = (
                "\n输出必须为严格符合下列 JSON Schema 的单个 JSON 对象。"
                "字段名、枚举和const必须逐字一致；不要Markdown或额外解释。\n"
                + json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
            )
            copied = [dict(message) for message in messages]
            if copied and copied[0].get("role") == "system":
                copied[0]["content"] = str(copied[0].get("content", "")) + instruction
            else:
                copied.insert(0, {"role": "system", "content": instruction})
            payload["messages"] = copied
        result = self.request("POST", "/api/chat", payload)
        if result.get("model") != MODEL_NAME or not isinstance(result.get("message"), dict):
            raise AIError("model_identity_mismatch", "返回的模型身份或消息结构不符合要求")
        if result.get("done") is not True:
            raise AIError("incomplete_response", "模型尚未完成响应")
        return result

    def structured_chat(self, messages: list[dict], response_type: type[BaseModel],
                        *, predict_tokens: int | None = None,
                        schema: dict | None = None) -> tuple[BaseModel, list[dict]]:
        """校验失败最多纠正一次；保留每次真实调用的指标，不修补或猜测字段值。"""
        conversation = [dict(message) for message in messages]
        responses = []
        effective_schema = schema or response_type.model_json_schema()
        Draft202012Validator.check_schema(effective_schema)
        for attempt in range(2):
            response = self.chat(conversation, schema=effective_schema,
                                 predict_tokens=predict_tokens)
            responses.append(response)
            try:
                parsed = parse_structured(response, response_type)
                try:
                    Draft202012Validator(effective_schema).validate(parsed.model_dump(mode="json"))
                except Exception as error:
                    raise AIError("schema_validation_failed", "模型输出未通过本任务的字段/证据约束") from error
                return parsed, responses
            except AIError as exc:
                if attempt:
                    exc.attempt_metrics = [metrics(item) for item in responses]
                    raise
                conversation.extend([
                    response["message"],
                    {"role": "user", "content": (
                        "上一次JSON未通过Schema。请重新按系统给出的Schema输出："
                        "包含所有required字段，字段名和const/enum逐字一致，不能增加其他字段。"
                        "不要把内容包在Markdown中，不要编造证据。"
                    )},
                ])
        raise AssertionError("unreachable")


def parse_structured(response: dict, response_type: type[BaseModel]) -> BaseModel:
    """同时执行 JSON Schema 与 Python 类型校验；失败不保存为成功结果。"""
    content = response.get("message", {}).get("content", "")
    try:
        data = json.loads(content)
        Draft202012Validator(response_type.model_json_schema()).validate(data)
        return response_type.model_validate(data, strict=True)
    except Exception as exc:
        # 只返回错误类别，避免把未经处理的网页或模型输出写入日志。
        raise AIError("schema_validation_failed", "模型输出未通过 JSON Schema/Python 校验") from exc


def metrics(response: dict) -> dict:
    return {key: response.get(key) for key in (
        "model", "total_duration", "load_duration", "prompt_eval_count",
        "prompt_eval_duration", "eval_count", "eval_duration", "done_reason",
    )}
