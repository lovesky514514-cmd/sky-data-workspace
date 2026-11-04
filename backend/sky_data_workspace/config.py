from pathlib import Path
import os
import sys
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

MODEL_NAME = "qwen3.5:9b"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
BUNDLE_ROOT = Path(getattr(sys, "_MEIPASS", PROJECT_ROOT))
DEFAULT_KNOWLEDGE = (
    BUNDLE_ROOT / "knowledge/knowledge.sqlite3" if getattr(sys, "frozen", False)
    else PROJECT_ROOT / "artifacts/bundle/knowledge.sqlite3"
)
DEFAULT_DATA = Path(os.environ.get("LOCALAPPDATA", str(PROJECT_ROOT))) / "SKYDataWorkspace" if getattr(sys, "frozen", False) else PROJECT_ROOT / "workspace_data"


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    model: Literal["qwen3.5:9b"] = MODEL_NAME
    ollama_url: str = "http://127.0.0.1:11434"
    ai_enabled: bool = True
    timeout_seconds: float = Field(default=240, ge=1, le=600)
    context_tokens: int = Field(default=4096, ge=2048, le=16384)
    predict_tokens: int = Field(default=512, ge=64, le=2048)
    cpu_threads: int = Field(default=4, ge=1, le=16)
    gpu_layers: Literal[0, -1] = 0
    knowledge_db: Path = DEFAULT_KNOWLEDGE
    data_dir: Path = DEFAULT_DATA

    @field_validator("ollama_url")
    @classmethod
    def local_only(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "::1", "localhost"}
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or parsed.path not in {"", "/"}):
            raise ValueError("Ollama 仅允许本机回环 HTTP 地址")
        if not 1 <= (parsed.port or 80) <= 65535:
            raise ValueError("Ollama 端口无效")
        return value.rstrip("/")
