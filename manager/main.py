"""
vLLM Multi-DGX Platform - Manager API
FastAPI application for managing models, API keys, and routing
"""

from fastapi import FastAPI, HTTPException, Depends, Header, Request
from starlette.requests import ClientDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import create_engine, Column, String, Integer, Float, Boolean, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session, relationship
from sqlalchemy.exc import IntegrityError
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any, Deque
from datetime import datetime, timedelta
import json
from collections import deque
import secrets
import logging
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
import time
import requests
import httpx
import subprocess
import os
import socket
import math
from urllib.parse import urlparse

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Database setup
DATABASE_URL = "sqlite:///./vllm_platform.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

PLATFORM_DIR = "/home/nvidia/reap/vllm-platform"
ENV_FILE = os.path.join(PLATFORM_DIR, ".env")
ROUND_ROBIN_STATE: Dict[str, int] = {}

APISIX_ADMIN_URL = os.getenv("APISIX_ADMIN_URL", "http://localhost:9180/apisix/admin")
APISIX_ADMIN_KEY = os.getenv("APISIX_ADMIN_KEY", "vllm-platform-admin-key-2026")
MANAGER_INTERNAL_URL = os.getenv("MANAGER_INTERNAL_URL", "http://172.30.140.142:8001")

# Prometheus metrics
request_counter = Counter('manager_requests_total', 'Total requests', ['endpoint', 'method'])
token_counter = Counter('tokens_processed_total', 'Total tokens processed', ['api_key', 'model'])
request_duration = Histogram('request_duration_seconds', 'Request duration', ['endpoint'])
tool_call_malformed_counter = Counter('manager_tool_calls_malformed_total', 'Malformed tool call data', ['stage', 'reason'])
tool_call_fallback_counter = Counter('manager_tool_calls_fallback_total', 'Tool call fallback actions', ['stage', 'action'])

try:
    TOOL_CALL_DEBUG_MAX = int(os.getenv("TOOL_CALL_DEBUG_MAX", "200"))
except Exception:
    TOOL_CALL_DEBUG_MAX = 200
TOOL_CALL_DEBUG_BUFFER: Deque[Dict[str, Any]] = deque(maxlen=TOOL_CALL_DEBUG_MAX)

# Models
class Model(Base):
    __tablename__ = "models"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    backend_host = Column(String)  # dgx-01, dgx-02, etc.
    backend_port = Column(Integer, default=8000)
    enabled = Column(Boolean, default=True)
    description = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "backend_host": self.backend_host,
            "backend_port": self.backend_port,
            "backend_url": f"http://{self.backend_host}:{self.backend_port}",
            "enabled": self.enabled,
            "description": self.description,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }


class Server(Base):
    __tablename__ = "servers"

    id = Column(Integer, primary_key=True, index=True)
    hostname = Column(String, unique=True, index=True)
    port = Column(Integer, default=8000)
    description = Column(String, nullable=True)
    enabled = Column(Boolean, default=True)
    last_checked_at = Column(DateTime, nullable=True)
    last_ok = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "hostname": self.hostname,
            "port": self.port,
            "description": self.description,
            "enabled": self.enabled,
            "last_checked_at": self.last_checked_at.isoformat() if self.last_checked_at else None,
            "last_ok": self.last_ok,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }


class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    email = Column(String, unique=True, index=True, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    api_keys = relationship("APIKey", back_populates="user")


class APIKey(Base):
    __tablename__ = "api_keys"
    
    id = Column(Integer, primary_key=True, index=True)
    key = Column(String, unique=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    name = Column(String)
    enabled = Column(Boolean, default=True)
    
    # Limits
    max_tokens_per_day = Column(Integer, default=100000)
    max_tokens_per_month = Column(Integer, default=1000000)
    rate_limit_per_minute = Column(Integer, default=100)
    rate_limit_window_seconds = Column(Integer, default=60)
    max_sessions = Column(Integer, default=5)
    session_ttl_seconds = Column(Integer, default=3600)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    last_used_at = Column(DateTime, nullable=True)
    
    user = relationship("User", back_populates="api_keys")
    usage_records = relationship("TokenUsage", back_populates="api_key")


class SessionRecord(Base):
    __tablename__ = "sessions"
    __table_args__ = (UniqueConstraint("api_key_id", "session_id", name="uq_session_key"),)
    
    id = Column(Integer, primary_key=True, index=True)
    api_key_id = Column(Integer, ForeignKey("api_keys.id"))
    session_id = Column(String, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_seen_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime)


class TokenUsage(Base):
    __tablename__ = "token_usage"
    
    id = Column(Integer, primary_key=True, index=True)
    api_key_id = Column(Integer, ForeignKey("api_keys.id"))
    model_name = Column(String)
    prompt_tokens = Column(Integer)
    completion_tokens = Column(Integer)
    total_tokens = Column(Integer)
    timestamp = Column(DateTime, default=datetime.utcnow)
    
    api_key = relationship("APIKey", back_populates="usage_records")


# Create tables
Base.metadata.create_all(bind=engine)

# Pydantic models
class ModelCreate(BaseModel):
    name: str
    backend_host: str
    backend_port: int = 8000
    description: Optional[str] = None


class ModelResponse(BaseModel):
    id: int
    name: str
    backend_host: str
    backend_port: int
    backend_url: str
    enabled: bool
    description: Optional[str]
    created_at: Optional[str]


class ServerCreate(BaseModel):
    hostname: str
    port: int = 8000
    description: Optional[str] = None


class ServerResponse(BaseModel):
    id: int
    hostname: str
    port: int
    description: Optional[str]
    enabled: bool
    last_checked_at: Optional[str]
    last_ok: bool
    created_at: Optional[str]


class ServerTestRequest(BaseModel):
    hostname: str
    port: int = 8000


class ServerTestResponse(BaseModel):
    ok: bool
    hostname: str
    port: int
    ping_ok: bool
    port_ok: bool
    error: Optional[str] = None


class UserCreate(BaseModel):
    username: str
    email: Optional[str] = None


class APIKeyCreate(BaseModel):
    user_id: int
    name: str


class APIKeyResponse(BaseModel):
    id: int
    key: str
    user_id: int
    name: str
    enabled: bool
    last_used_at: Optional[str] = None


class APIKeyUpdate(BaseModel):
    enabled: Optional[bool] = None
    name: Optional[str] = None


class ResolveModelRequest(BaseModel):
    model: str


class ResolveModelResponse(BaseModel):
    backend_url: str
    model_name: str


class UsageReportRequest(BaseModel):
    api_key: str
    user_id: Optional[int] = None
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    session_id: Optional[str] = None


class VLLMTestRequest(BaseModel):
    backend_host: str
    backend_port: int = 8000


class VLLMTestResponse(BaseModel):
    ok: bool
    endpoint: str
    models: List[str] = []
    error: Optional[str] = None


class EnvUpdateRequest(BaseModel):
    values: Dict[str, str]


# FastAPI app
app = FastAPI(title="vLLM Platform Manager API", version="1.0.0")

# CORS
cors_origins_env = os.getenv("CORS_ORIGINS", "").strip()
if cors_origins_env:
    cors_origins = [origin.strip() for origin in cors_origins_env.split(",") if origin.strip()]
else:
    cors_origins = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://172.30.140.142:5173",
    ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_tasks():
    _ensure_apisix_routes()

# Database dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _run_script(script_name: str) -> Dict[str, Any]:
    script_path = os.path.join(PLATFORM_DIR, script_name)
    if not os.path.exists(script_path):
        raise HTTPException(status_code=404, detail=f"Script not found: {script_name}")

    result = subprocess.run(
        ["/bin/bash", script_path],
        cwd=PLATFORM_DIR,
        capture_output=True,
        text=True
    )
    return {
        "ok": result.returncode == 0,
        "code": result.returncode,
        "stdout": result.stdout[-8000:],
        "stderr": result.stderr[-8000:]
    }


def _read_env_file() -> Dict[str, str]:
    env = {}
    if not os.path.exists(ENV_FILE):
        return env
    with open(ENV_FILE, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip()
    return env


def _write_env_file(values: Dict[str, str]) -> None:
    existing = _read_env_file()
    existing.update(values)
    lines = ["# vLLM Platform Configuration\n"]
    for key, value in existing.items():
        lines.append(f"{key}={value}\n")
    with open(ENV_FILE, "w", encoding="utf-8") as handle:
        handle.writelines(lines)


def _get_env_setting(key: str, fallback: str) -> str:
    return os.getenv(key) or _read_env_file().get(key) or fallback


def _require_admin_key(request: Request) -> None:
    admin_key = _get_env_setting("APISIX_ADMIN_KEY", APISIX_ADMIN_KEY)
    provided = request.headers.get("X-Admin-Key") or request.headers.get("X-API-KEY")
    if not provided or provided != admin_key:
        raise HTTPException(status_code=403, detail="Forbidden")


def _parse_host_port(url: str) -> tuple[str, int]:
    parsed = urlparse(url)
    host = parsed.hostname or "localhost"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return host, port


def _normalize_content_blocks(content: Any) -> List[Dict[str, str]]:
    if content is None:
        return [{"type": "text", "text": ""}]
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if isinstance(content, list):
        blocks: List[Dict[str, str]] = []
        for item in content:
            if isinstance(item, dict) and "type" in item and "text" in item:
                blocks.append({"type": item["type"], "text": item["text"]})
            elif isinstance(item, str):
                blocks.append({"type": "text", "text": item})
        if blocks:
            return blocks
    return [{"type": "text", "text": ""}]


def _messages_to_string(messages: Any) -> List[Dict[str, Any]]:
    if not isinstance(messages, list):
        return []
    normalized: List[Dict[str, Any]] = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")
        content = msg.get("content")
        text = ""
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            parts: List[str] = []
            for item in content:
                if isinstance(item, dict):
                    if item.get("type") == "text":
                        parts.append(str(item.get("text", "")))
                elif isinstance(item, str):
                    parts.append(item)
            text = "".join(parts)
        elif content is None:
            text = ""
        else:
            text = str(content)
        if role:
            normalized.append({"role": role, "content": text})
    return normalized


def _sanitize_stream_options(options: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(options, dict):
        return None
    include_usage = options.get("include_usage")
    if isinstance(include_usage, bool):
        return {"include_usage": include_usage}
    return None


def _record_tool_call_debug(source: str, model: Optional[str], payload: Any, raw: Optional[str] = None) -> None:
    try:
        tool_call_info: Dict[str, Any] = {}
        if isinstance(payload, list):
            tool_call_info = _analyze_tool_call_format(payload)
        elif isinstance(payload, dict) and isinstance(payload.get("tool_calls"), list):
            tool_call_info = _analyze_tool_call_format(payload.get("tool_calls"))
        entry = {
            "ts": datetime.utcnow().isoformat() + "Z",
            "source": source,
            "model": model,
            "payload": payload,
            "kilo_format": "yes" if _is_kilo_tool_calls(payload) else "no",
            **tool_call_info,
        }
        if raw is not None:
            entry["raw"] = raw
        TOOL_CALL_DEBUG_BUFFER.append(entry)
    except Exception:
        logger.exception("Failed to record tool-call debug entry")


def _log_tool_call_issue(stage: str, reason: str, detail: Optional[str] = None) -> None:
    if detail:
        logger.warning("Tool call issue (%s): %s (%s)", stage, reason, detail)
    else:
        logger.warning("Tool call issue (%s): %s", stage, reason)
    try:
        tool_call_malformed_counter.labels(stage=stage, reason=reason).inc()
    except Exception:
        logger.exception("Failed to increment tool_call_malformed_counter")


def _validate_tool_calls(tool_calls: Any, stage: str, require_json_args: bool = True) -> bool:
    if not isinstance(tool_calls, list) or not tool_calls:
        _log_tool_call_issue(stage, "not_list_or_empty")
        return False
    ok = True
    for call in tool_calls:
        if not isinstance(call, dict):
            ok = False
            _log_tool_call_issue(stage, "call_not_dict")
            continue
        if not isinstance(call.get("id"), str):
            ok = False
            _log_tool_call_issue(stage, "missing_id")
        if call.get("type") != "function":
            ok = False
            _log_tool_call_issue(stage, "invalid_type", str(call.get("type")))
        function = call.get("function") if "function" in call else None
        if function is None and isinstance(call.get("name"), str):
            # Kilo shorthand format
            function = {"name": call.get("name"), "arguments": call.get("arguments")}
        if not isinstance(function, dict):
            ok = False
            _log_tool_call_issue(stage, "missing_function")
            continue
        name = function.get("name")
        if not isinstance(name, str) or not name.strip():
            ok = False
            _log_tool_call_issue(stage, "missing_name")
        args = function.get("arguments")
        if isinstance(args, dict) and not require_json_args:
            continue
        if not isinstance(args, str):
            ok = False
            _log_tool_call_issue(stage, "arguments_not_string")
        elif require_json_args:
            try:
                json.loads(args)
            except Exception:
                ok = False
                _log_tool_call_issue(stage, "arguments_not_json")
    return ok


def _validate_tool_calls_for_kilo(tool_calls: Any, stage: str) -> bool:
    if not isinstance(tool_calls, list) or not tool_calls:
        _log_tool_call_issue(stage, "not_list_or_empty")
        return False
    for call in tool_calls:
        if not isinstance(call, dict):
            _log_tool_call_issue(stage, "call_not_dict")
            return False
        if "function" not in call and isinstance(call.get("name"), str):
            continue
        function = call.get("function")
        if not isinstance(function, dict):
            _log_tool_call_issue(stage, "missing_function")
            return False
        args = function.get("arguments")
        if args is not None:
            if isinstance(args, dict):
                continue
            if not isinstance(args, str):
                _log_tool_call_issue(stage, "arguments_not_string")
                return False
            if args.strip():
                try:
                    json.loads(args)
                except Exception:
                    continue
    return True


def _is_kilo_tool_calls(payload: Any) -> bool:
    tool_calls = payload
    if isinstance(payload, dict):
        tool_calls = payload.get("tool_calls")
    if not isinstance(tool_calls, list):
        return False
    for call in tool_calls:
        if not isinstance(call, dict):
            continue
        function = call.get("function")
        if isinstance(call.get("name"), str) and function is None:
            return True
        if isinstance(function, dict) and isinstance(function.get("arguments"), dict):
            return True
    return False


def _analyze_tool_call_format(tool_calls: List[Dict[str, Any]]) -> Dict[str, Any]:
    counts = {"total": 0, "args_string": 0, "args_object": 0, "args_other": 0, "shorthand": 0}
    for call in tool_calls:
        if not isinstance(call, dict):
            continue
        counts["total"] += 1
        if "function" not in call and isinstance(call.get("name"), str):
            counts["shorthand"] += 1
            continue
        function = call.get("function") if isinstance(call.get("function"), dict) else None
        if not function:
            counts["args_other"] += 1
            continue
        args = function.get("arguments")
        if isinstance(args, str):
            counts["args_string"] += 1
        elif isinstance(args, dict):
            counts["args_object"] += 1
        else:
            counts["args_other"] += 1
    return {"tool_call_format": counts}


def _validate_chat_chunk(payload: Dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        logger.warning("/proxy/chat/completions invalid chunk: not a dict")
        return
    if payload.get("object") != "chat.completion.chunk":
        logger.warning("/proxy/chat/completions invalid chunk object: %r", payload.get("object"))
    if not isinstance(payload.get("id"), str):
        logger.warning("/proxy/chat/completions invalid chunk id: %r", payload.get("id"))
    if not isinstance(payload.get("model"), str):
        logger.warning("/proxy/chat/completions invalid chunk model: %r", payload.get("model"))
    choices = payload.get("choices")
    if not isinstance(choices, list):
        logger.warning("/proxy/chat/completions invalid chunk choices: %r", type(choices))
        return
    for choice in choices:
        if not isinstance(choice, dict):
            logger.warning("/proxy/chat/completions invalid chunk choice type: %r", type(choice))
            continue
        if "index" not in choice or not isinstance(choice.get("index"), int):
            logger.warning("/proxy/chat/completions invalid chunk choice index: %r", choice.get("index"))
        delta = choice.get("delta")
        if not isinstance(delta, dict):
            logger.warning("/proxy/chat/completions invalid chunk delta: %r", type(delta))
            continue
        tool_calls = delta.get("tool_calls")
        if tool_calls is not None:
            _validate_tool_calls_for_kilo(tool_calls, stage="stream_chunk")


def _validate_chat_response(payload: Dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        logger.warning("/proxy/chat/completions invalid response: not a dict")
        return
    if payload.get("object") != "chat.completion":
        logger.warning("/proxy/chat/completions invalid response object: %r", payload.get("object"))
    if not isinstance(payload.get("id"), str):
        logger.warning("/proxy/chat/completions invalid response id: %r", payload.get("id"))
    if not isinstance(payload.get("model"), str):
        logger.warning("/proxy/chat/completions invalid response model: %r", payload.get("model"))
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        logger.warning("/proxy/chat/completions invalid response choices: %r", choices)
        return
    choice = choices[0]
    if not isinstance(choice, dict):
        logger.warning("/proxy/chat/completions invalid response choice type: %r", type(choice))
        return
    if choice.get("finish_reason") == "tool_calls":
        message = choice.get("message")
        if not isinstance(message, dict) or message.get("tool_calls") is None:
            logger.warning("/proxy/chat/completions finish_reason tool_calls without tool_calls payload")
    message = choice.get("message")
    if not isinstance(message, dict):
        logger.warning("/proxy/chat/completions invalid response message: %r", type(message))
        return
    if message.get("role") != "assistant":
        logger.warning("/proxy/chat/completions invalid response role: %r", message.get("role"))
    tool_calls = message.get("tool_calls")
    if tool_calls is not None:
        _validate_tool_calls(tool_calls, stage="non_stream_out", require_json_args=True)


def _normalize_tool_calls(tool_calls: Any, allow_partial_args: bool = False) -> Any:
    if not isinstance(tool_calls, list):
        return tool_calls
    normalized: List[Dict[str, Any]] = []
    for i, call in enumerate(tool_calls):
        if not isinstance(call, dict):
            continue
        function = call.get("function", {})
        if isinstance(function, str):
            try:
                function = json.loads(function)
            except Exception:
                function = {"name": function, "arguments": call.get("arguments")}
        if not isinstance(function, dict):
            function = {"name": str(function), "arguments": call.get("arguments")}

        explicit_empty = False
        args = function.get("arguments", None)
        if isinstance(args, str):
            if not args.strip():
                explicit_empty = True
                function["arguments"] = ""
            else:
                try:
                    json.loads(args)
                    function["arguments"] = args
                except Exception:
                    if allow_partial_args:
                        function["arguments"] = args
                    else:
                        function["arguments"] = json.dumps({"input": args})
                        try:
                            tool_call_fallback_counter.labels(stage="normalize", action="wrapped_input").inc()
                        except Exception:
                            logger.exception("Failed to increment tool_call_fallback_counter")
        elif isinstance(args, dict):
            if not args:
                explicit_empty = True
            function["arguments"] = json.dumps(args)
        elif args is None:
            function["arguments"] = None
        else:
            if allow_partial_args:
                function["arguments"] = str(args)
            else:
                function["arguments"] = json.dumps({"input": str(args)})
                try:
                    tool_call_fallback_counter.labels(stage="normalize", action="wrapped_input").inc()
                except Exception:
                    logger.exception("Failed to increment tool_call_fallback_counter")

        normalized.append({
            "id": call.get("id", f"call_{secrets.token_hex(8)}"),
            "type": "function",
            "function": function,
            "index": call.get("index", i),
            "_explicit_empty_args": explicit_empty,
        })
    return normalized


def _fix_tool_calls(tool_calls: Any, allow_partial_args: bool = False) -> Any:
    if not isinstance(tool_calls, list):
        return tool_calls
    normalized = _normalize_tool_calls(tool_calls, allow_partial_args=allow_partial_args)
    if allow_partial_args:
        for call in normalized:
            if isinstance(call, dict):
                call.pop("_explicit_empty_args", None)
        return normalized

    fixed: List[Dict[str, Any]] = []
    for call in normalized:
        if not isinstance(call, dict):
            _log_tool_call_issue("normalize", "call_not_dict")
            continue
        explicit_empty = bool(call.pop("_explicit_empty_args", False))
        function = call.get("function") if isinstance(call, dict) else None
        if not isinstance(function, dict):
            _log_tool_call_issue("normalize", "missing_function")
            continue
        name = function.get("name", "")
        if not isinstance(name, str) or not name.strip():
            _log_tool_call_issue("normalize", "missing_name")
            continue

        args_raw = function.get("arguments")
        args: Optional[Dict[str, Any]] = None
        if isinstance(args_raw, str):
            if not args_raw.strip():
                args = {} if explicit_empty else None
            else:
                try:
                    args = json.loads(args_raw)
                except Exception:
                    args = None
        elif isinstance(args_raw, dict):
            args = args_raw

        if args is None:
            _log_tool_call_issue("normalize", "arguments_invalid")
            try:
                tool_call_fallback_counter.labels(stage="normalize", action="drop_tool_call").inc()
            except Exception:
                logger.exception("Failed to increment tool_call_fallback_counter")
            continue

        if not isinstance(args, dict):
            args = {"input": args}
            try:
                tool_call_fallback_counter.labels(stage="normalize", action="wrapped_input").inc()
            except Exception:
                logger.exception("Failed to increment tool_call_fallback_counter")

        if name == "search_files" and not explicit_empty:
            args.setdefault("path", ".")
            args.setdefault("regex", ".*")
            args.setdefault("file_pattern", "*.*")
            try:
                tool_call_fallback_counter.labels(stage="normalize", action="defaults_applied").inc()
            except Exception:
                logger.exception("Failed to increment tool_call_fallback_counter")
        elif name == "list_files" and not explicit_empty:
            args.setdefault("path", ".")
            args.setdefault("recursive", False)
            try:
                tool_call_fallback_counter.labels(stage="normalize", action="defaults_applied").inc()
            except Exception:
                logger.exception("Failed to increment tool_call_fallback_counter")

        function["arguments"] = json.dumps(args)
        call["function"] = function
        fixed.append(call)
    return fixed


def _accumulate_tool_calls(
    accumulators: Dict[int, Dict[str, Any]],
    tool_calls: List[Dict[str, Any]],
) -> None:
    for tc in tool_calls:
        if not isinstance(tc, dict):
            continue
        idx = tc.get("index", 0)
        function = tc.get("function") if isinstance(tc.get("function"), dict) else {}
        name = function.get("name", "")
        args_piece = function.get("arguments")

        if idx not in accumulators:
            accumulators[idx] = {
                "id": tc.get("id", f"call_{secrets.token_hex(8)}"),
                "type": "function",
                "index": idx,
                "function": {"name": name, "arguments": ""},
            }

        if name and not accumulators[idx]["function"].get("name"):
            accumulators[idx]["function"]["name"] = name

        if isinstance(args_piece, str):
            # If this chunk is a full JSON object, replace; else append
            if args_piece:
                trimmed = args_piece.strip()
                if trimmed.startswith("{") and trimmed.endswith("}"):
                    try:
                        json.loads(trimmed)
                        accumulators[idx]["function"]["arguments"] = trimmed
                        continue
                    except Exception:
                        pass
                accumulators[idx]["function"]["arguments"] += args_piece
            else:
                accumulators[idx]["function"].setdefault("_explicit_empty_args", True)


def _finalize_tool_call_accumulators(accumulators: Dict[int, Dict[str, Any]]) -> List[Dict[str, Any]]:
    finalized: List[Dict[str, Any]] = []
    for idx, tc in sorted(accumulators.items(), key=lambda item: item[0]):
        if not isinstance(tc, dict):
            _log_tool_call_issue("stream_finalize", "call_not_dict")
            continue
        function = tc.get("function") if isinstance(tc.get("function"), dict) else {}
        name = function.get("name", "")
        if not isinstance(name, str) or not name.strip():
            _log_tool_call_issue("stream_finalize", "missing_name")
            continue

        explicit_empty = bool(function.pop("_explicit_empty_args", False))
        args_str = function.get("arguments", "")
        if not isinstance(args_str, str):
            _log_tool_call_issue("stream_finalize", "arguments_not_string")
            continue
        if not args_str.strip():
            if explicit_empty:
                args_str = "{}"
                try:
                    tool_call_fallback_counter.labels(stage="stream_finalize", action="explicit_empty").inc()
                except Exception:
                    logger.exception("Failed to increment tool_call_fallback_counter")
            else:
                _log_tool_call_issue("stream_finalize", "arguments_missing")
                continue
        try:
            json.loads(args_str)
        except Exception:
            args_str = json.dumps({"input": args_str})
            try:
                tool_call_fallback_counter.labels(stage="stream_finalize", action="wrapped_input").inc()
            except Exception:
                logger.exception("Failed to increment tool_call_fallback_counter")

        function["arguments"] = args_str
        tc["function"] = function
        if not isinstance(tc.get("id"), str):
            tc["id"] = f"call_{secrets.token_hex(8)}"
        tc["type"] = "function"
        tc["index"] = idx
        finalized.append(tc)
    return finalized


def _coerce_max_tokens(value: Any, default: int = 2048) -> int:
    if isinstance(value, bool):
        return default
    try:
        if value is None:
            return default
        if isinstance(value, str) and not value.strip():
            return default
        tokens = int(float(value))
    except Exception:
        return default
    return tokens if tokens >= 1 else 1


def _coerce_positive_int(value: Any, fallback: int) -> int:
    if isinstance(value, bool):
        return fallback
    try:
        if value is None:
            return fallback
        if isinstance(value, str) and not value.strip():
            return fallback
        number = int(float(value))
    except Exception:
        return fallback
    return number if number >= 1 else fallback


def _get_int_env_setting(keys: List[str], fallback: int) -> int:
    env_values = _read_env_file()
    for key in keys:
        raw = os.getenv(key) or env_values.get(key)
        if raw is None:
            continue
        value = _coerce_positive_int(raw, fallback)
        if value >= 1:
            return value
    return fallback


def _estimate_prompt_tokens(messages: Any, chars_per_token: float) -> Optional[int]:
    if not isinstance(messages, list):
        return None
    total_chars = 0
    msg_count = 0
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        content = msg.get("content", "")
        total_chars += len(str(content))
        msg_count += 1
    if msg_count == 0:
        return 0
    estimated = (total_chars / chars_per_token) + (msg_count * 4)
    return max(0, int(math.ceil(estimated)))


def _ensure_apisix_routes() -> None:
    apisix_admin = _get_env_setting("APISIX_ADMIN_URL", APISIX_ADMIN_URL)
    admin_key = _get_env_setting("APISIX_ADMIN_KEY", APISIX_ADMIN_KEY)
    manager_url = _get_env_setting("MANAGER_INTERNAL_URL", MANAGER_INTERNAL_URL)
    manager_host, manager_port = _parse_host_port(manager_url)

    route_config = {
        "uri": "/v1/chat/completions",
        "methods": ["POST"],
        "plugins": {
            "proxy-rewrite": {
                "regex_uri": ["^/v1/chat/completions$", "/proxy/chat/completions"]
            },
            "prometheus": {}
        },
        "upstream": {
            "type": "roundrobin",
            "nodes": {f"{manager_host}:{manager_port}": 1},
            "timeout": {
                "connect": 60,
                "send": 60,
                "read": 60
            }
        }
    }

    models_route = {
        "uri": "/v1/models",
        "methods": ["GET"],
        "plugins": {
            "proxy-rewrite": {
                "regex_uri": ["^/v1/models$", "/proxy/models"]
            },
            "prometheus": {}
        },
        "upstream": {
            "type": "roundrobin",
            "nodes": {f"{manager_host}:{manager_port}": 1},
            "timeout": {
                "connect": 60,
                "send": 60,
                "read": 60
            }
        }
    }

    responses_route = {
        "uri": "/v1/responses",
        "methods": ["POST"],
        "plugins": {
            "proxy-rewrite": {
                "regex_uri": ["^/v1/responses$", "/proxy/responses"]
            },
            "prometheus": {}
        },
        "upstream": {
            "type": "roundrobin",
            "nodes": {f"{manager_host}:{manager_port}": 1},
            "timeout": {
                "connect": 60,
                "send": 60,
                "read": 60
            }
        }
    }

    health_route = {
        "uri": "/health",
        "methods": ["GET"],
        "plugins": {"prometheus": {}},
        "upstream": {
            "type": "roundrobin",
            "nodes": {f"{manager_host}:{manager_port}": 1}
        }
    }

    try:
        requests.put(
            f"{apisix_admin}/routes/1",
            headers={"X-API-KEY": admin_key, "Content-Type": "application/json"},
            json=route_config,
            timeout=3
        )
        requests.put(
            f"{apisix_admin}/routes/2",
            headers={"X-API-KEY": admin_key, "Content-Type": "application/json"},
            json=models_route,
            timeout=3
        )
        requests.put(
            f"{apisix_admin}/routes/3",
            headers={"X-API-KEY": admin_key, "Content-Type": "application/json"},
            json=responses_route,
            timeout=3
        )
        requests.put(
            f"{apisix_admin}/routes/4",
            headers={"X-API-KEY": admin_key, "Content-Type": "application/json"},
            json=health_route,
            timeout=3
        )
    except Exception as exc:
        logger.warning(f"APISIX route setup skipped: {exc}")


def _test_server_endpoint(hostname: str, port: int) -> Dict[str, Any]:
    endpoint = f"http://{hostname}:{port}/v1/models"
    try:
        response = requests.get(endpoint, timeout=3)
        if response.status_code != 200:
            return {
                "ok": False,
                "hostname": hostname,
                "port": port,
                "ping_ok": True,
                "port_ok": False,
                "error": f"HTTP {response.status_code}"
            }
        return {
            "ok": True,
            "hostname": hostname,
            "port": port,
            "ping_ok": True,
            "port_ok": True,
            "error": None
        }
    except requests.exceptions.ConnectionError:
        return {
            "ok": False,
            "hostname": hostname,
            "port": port,
            "ping_ok": False,
            "port_ok": False,
            "error": "Connection error"
        }
    except requests.exceptions.Timeout:
        return {
            "ok": False,
            "hostname": hostname,
            "port": port,
            "ping_ok": False,
            "port_ok": False,
            "error": "Timeout"
        }
    except Exception as exc:
        return {
            "ok": False,
            "hostname": hostname,
            "port": port,
            "ping_ok": False,
            "port_ok": False,
            "error": str(exc)
        }


def _get_primary_ip() -> str:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        return ip
    except Exception:
        return "127.0.0.1"


# Validate API key
async def validate_api_key(authorization: str = Header(None), db: Session = Depends(get_db)) -> APIKey:
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing authorization header")
    
    # Extract key from "Bearer <key>" format
    if authorization.startswith("Bearer "):
        key = authorization[7:]
    else:
        key = authorization
    
    api_key = db.query(APIKey).filter(APIKey.key == key, APIKey.enabled == True).first()
    if not api_key:
        raise HTTPException(status_code=401, detail="Invalid or disabled API key")
    
    # Update last used
    api_key.last_used_at = datetime.utcnow()
    db.commit()
    
    return api_key


# Routes
@app.get("/")
async def root():
    return {
        "name": "vLLM Platform Manager API",
        "version": "1.0.0",
        "status": "operational"
    }


@app.get("/health")
async def health():
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}


# Server registry
@app.get("/servers", response_model=List[ServerResponse])
async def list_servers(db: Session = Depends(get_db)):
    servers = db.query(Server).filter(Server.enabled == True).all()
    return [server.to_dict() for server in servers]


@app.post("/servers/test", response_model=ServerTestResponse)
async def test_server(payload: ServerTestRequest):
    return _test_server_endpoint(payload.hostname, payload.port)


@app.post("/servers", response_model=ServerResponse)
async def create_server(server: ServerCreate, db: Session = Depends(get_db)):
    existing = db.query(Server).filter(Server.hostname == server.hostname).first()
    if existing:
        raise HTTPException(status_code=400, detail="Server already exists")

    test_result = _test_server_endpoint(server.hostname, server.port)
    if not test_result["ok"]:
        raise HTTPException(status_code=400, detail=test_result.get("error") or "Server unreachable")

    db_server = Server(
        hostname=server.hostname,
        port=server.port,
        description=server.description,
        last_checked_at=datetime.utcnow(),
        last_ok=True
    )
    db.add(db_server)
    db.commit()
    db.refresh(db_server)
    return db_server.to_dict()


@app.delete("/servers/{server_id}")
async def delete_server(server_id: int, db: Session = Depends(get_db)):
    server = db.query(Server).filter(Server.id == server_id).first()
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    db.delete(server)
    db.commit()
    return {"status": "deleted", "server_id": server_id}


# Model management
@app.get("/models", response_model=List[ModelResponse])
async def list_models(db: Session = Depends(get_db)):
    """List all available models"""
    request_counter.labels(endpoint="/models", method="GET").inc()
    models = db.query(Model).filter(Model.enabled == True).all()
    return [model.to_dict() for model in models]


@app.post("/models", response_model=ModelResponse)
async def create_model(model: ModelCreate, db: Session = Depends(get_db)):
    """Create a new model registration"""
    request_counter.labels(endpoint="/models", method="POST").inc()
    
    # Check if model already exists
    existing = db.query(Model).filter(Model.name == model.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Model already exists")
    
    db_model = Model(
        name=model.name,
        backend_host=model.backend_host,
        backend_port=model.backend_port,
        description=model.description
    )
    db.add(db_model)
    db.commit()
    db.refresh(db_model)
    
    logger.info(f"Created model: {model.name} -> {model.backend_host}:{model.backend_port}")
    return db_model.to_dict()


@app.post("/models/test", response_model=VLLMTestResponse)
async def test_vllm_endpoint(payload: VLLMTestRequest):
    """Test vLLM endpoint before registration"""
    endpoint = f"http://{payload.backend_host}:{payload.backend_port}"
    try:
        response = requests.get(f"{endpoint}/v1/models", timeout=5)
        if response.status_code != 200:
            return {"ok": False, "endpoint": endpoint, "error": f"HTTP {response.status_code}"}
        data = response.json()
        models = [item.get("id") for item in data.get("data", []) if item.get("id")]
        return {"ok": True, "endpoint": endpoint, "models": models}
    except requests.exceptions.Timeout:
        return {"ok": False, "endpoint": endpoint, "error": "Timeout"}
    except requests.exceptions.ConnectionError:
        return {"ok": False, "endpoint": endpoint, "error": "Connection error"}
    except Exception as exc:
        return {"ok": False, "endpoint": endpoint, "error": str(exc)}


@app.delete("/models/{model_id}")
async def delete_model(model_id: int, db: Session = Depends(get_db)):
    """Delete a model"""
    model = db.query(Model).filter(Model.id == model_id).first()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")

    db.delete(model)
    db.commit()
    logger.info(f"Deleted model: {model.name}")
    return {"status": "deleted", "model_id": model_id}


# User management
@app.post("/users")
async def create_user(user: UserCreate, db: Session = Depends(get_db)):
    """Create a new user"""
    existing = db.query(User).filter(User.username == user.username).first()
    if existing:
        raise HTTPException(status_code=400, detail="User already exists")

    if user.email:
        existing_email = db.query(User).filter(User.email == user.email).first()
        if existing_email:
            raise HTTPException(status_code=409, detail="Email already exists")
    
    db_user = User(username=user.username, email=user.email)
    db.add(db_user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="User with this email already exists")
    db.refresh(db_user)
    
    logger.info(f"Created user: {user.username}")
    return {"id": db_user.id, "username": db_user.username, "email": db_user.email}


@app.get("/users")
async def list_users(db: Session = Depends(get_db)):
    """List all users"""
    users = db.query(User).all()
    return [{"id": u.id, "username": u.username, "email": u.email, "is_active": u.is_active} for u in users]


@app.patch("/users/{user_id}")
async def update_user(user_id: int, payload: Dict[str, Any], db: Session = Depends(get_db)):
    """Update a user (enable/disable)"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if "is_active" in payload:
        user.is_active = bool(payload["is_active"])

    if "email" in payload:
        user.email = payload["email"]

    db.commit()
    return {"id": user.id, "username": user.username, "email": user.email, "is_active": user.is_active}


@app.delete("/users/{user_id}")
async def delete_user(user_id: int, db: Session = Depends(get_db)):
    """Delete a user and all API keys"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    key_ids = [k.id for k in db.query(APIKey).filter(APIKey.user_id == user_id).all()]
    if key_ids:
        db.query(TokenUsage).filter(TokenUsage.api_key_id.in_(key_ids)).delete(synchronize_session=False)
        db.query(SessionRecord).filter(SessionRecord.api_key_id.in_(key_ids)).delete(synchronize_session=False)
        db.query(APIKey).filter(APIKey.id.in_(key_ids)).delete(synchronize_session=False)

    db.delete(user)
    db.commit()

    return {"status": "deleted", "user_id": user_id}


# API key management
@app.post("/api-keys", response_model=APIKeyResponse)
async def create_api_key(key_data: APIKeyCreate, db: Session = Depends(get_db)):
    """Generate a new API key"""
    
    # Verify user exists
    user = db.query(User).filter(User.id == key_data.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Generate secure key
    key = f"vllm-{secrets.token_urlsafe(32)}"
    
    db_key = APIKey(
        key=key,
        user_id=key_data.user_id,
        name=key_data.name
    )
    db.add(db_key)
    db.commit()
    db.refresh(db_key)
    
    logger.info(f"Created API key for user {user.username}: {key_data.name}")
    return {
        "id": db_key.id,
        "key": db_key.key,
        "user_id": db_key.user_id,
        "name": db_key.name,
        "enabled": db_key.enabled,
        "last_used_at": db_key.last_used_at.isoformat() if db_key.last_used_at else None
    }


@app.get("/api-keys")
async def list_api_keys(mask: bool = True, db: Session = Depends(get_db)):
    """List all API keys"""
    keys = db.query(APIKey).all()
    response = []
    for k in keys:
        response.append({
            "id": k.id,
            "key": (k.key[:15] + "...") if mask else k.key,
            "user_id": k.user_id,
            "name": k.name,
            "enabled": k.enabled,
            "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None
        })
    return response


@app.patch("/api-keys/{key_id}")
async def update_api_key(key_id: int, payload: APIKeyUpdate, db: Session = Depends(get_db)):
    """Update API key settings"""
    db_key = db.query(APIKey).filter(APIKey.id == key_id).first()
    if not db_key:
        raise HTTPException(status_code=404, detail="API key not found")

    for field, value in payload.dict(exclude_unset=True).items():
        setattr(db_key, field, value)

    db.commit()
    return {
        "id": db_key.id,
        "key": db_key.key,
        "user_id": db_key.user_id,
        "name": db_key.name,
        "enabled": db_key.enabled,
        "last_used_at": db_key.last_used_at.isoformat() if db_key.last_used_at else None
    }


@app.delete("/api-keys/{key_id}")
async def delete_api_key(key_id: int, db: Session = Depends(get_db)):
    """Delete an API key"""
    db_key = db.query(APIKey).filter(APIKey.id == key_id).first()
    if not db_key:
        raise HTTPException(status_code=404, detail="API key not found")

    db.query(TokenUsage).filter(TokenUsage.api_key_id == key_id).delete(synchronize_session=False)
    db.query(SessionRecord).filter(SessionRecord.api_key_id == key_id).delete(synchronize_session=False)
    db.delete(db_key)
    db.commit()
    return {"status": "deleted", "key_id": key_id}


# Authentication endpoint for APISIX
@app.post("/auth/validate-key")
async def validate_key(request: Request, db: Session = Depends(get_db)):
    """Validate API key (called by APISIX)"""
    body = await request.json()
    api_key_value = body.get("key") or body.get("api_key")

    if not api_key_value:
        raise HTTPException(status_code=400, detail="Missing API key")

    api_key = db.query(APIKey).filter(APIKey.key == api_key_value, APIKey.enabled == True).first()
    if not api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")

    # Ensure user is active
    if api_key.user and not api_key.user.is_active:
        raise HTTPException(status_code=403, detail="User is disabled")

    return {
        "valid": True,
        "user_id": api_key.user_id
    }


# Model resolution
@app.post("/resolve-model", response_model=ResolveModelResponse)
async def resolve_model(request: ResolveModelRequest, db: Session = Depends(get_db)):
    """Resolve model name to backend URL"""
    start_time = time.time()
    
    model = db.query(Model).filter(Model.name == request.model, Model.enabled == True).first()
    if not model:
        raise HTTPException(status_code=404, detail=f"Model '{request.model}' not found")

    servers = db.query(Server).filter(Server.enabled == True).all()
    use_servers = str(model.backend_host or "").lower() in {"", "auto", "servers", "pool", "round_robin"}
    if servers and use_servers:
        index = ROUND_ROBIN_STATE.get(model.name, 0) % len(servers)
        selected = servers[index]
        ROUND_ROBIN_STATE[model.name] = index + 1
        host = selected.hostname
        if host in ["localhost", "127.0.0.1"]:
            host = _get_primary_ip()
        backend_url = f"http://{host}:{selected.port}"
    else:
        host = model.backend_host
        if host in ["localhost", "127.0.0.1"]:
            host = _get_primary_ip()
        backend_url = f"http://{host}:{model.backend_port}"
    
    duration = time.time() - start_time
    request_duration.labels(endpoint="/resolve-model").observe(duration)
    
    logger.info(f"Resolved model '{request.model}' to {backend_url}")
    return {"backend_url": backend_url, "model_name": model.name}


# Usage reporting
@app.post("/usage/report")
async def report_usage(usage: UsageReportRequest, db: Session = Depends(get_db)):
    """Report token usage"""
    
    # Find API key
    api_key = db.query(APIKey).filter(APIKey.key == usage.api_key).first()
    if not api_key:
        raise HTTPException(status_code=404, detail="API key not found")
    
    # Record usage
    usage_record = TokenUsage(
        api_key_id=api_key.id,
        model_name=usage.model,
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens,
        total_tokens=usage.total_tokens
    )
    db.add(usage_record)
    db.commit()
    
    # Update Prometheus metrics
    token_counter.labels(api_key=api_key.key[:15], model=usage.model).inc(usage.total_tokens)
    
    logger.info(f"Recorded usage: {usage.total_tokens} tokens for model {usage.model}")
    return {"status": "recorded", "tokens": usage.total_tokens}


@app.get("/usage/stats")
async def get_usage_stats(
    api_key_value: Optional[str] = None,
    days: int = 7,
    db: Session = Depends(get_db)
):
    """Get usage statistics"""
    
    query = db.query(TokenUsage)
    
    if api_key_value:
        api_key = db.query(APIKey).filter(APIKey.key == api_key_value).first()
        if api_key:
            query = query.filter(TokenUsage.api_key_id == api_key.id)
    
    # Filter by time range
    cutoff = datetime.utcnow() - timedelta(days=days)
    query = query.filter(TokenUsage.timestamp >= cutoff)
    
    usage_records = query.all()
    
    total_tokens = sum(u.total_tokens for u in usage_records)
    total_requests = len(usage_records)
    
    # Group by model
    by_model = {}
    for record in usage_records:
        if record.model_name not in by_model:
            by_model[record.model_name] = {"requests": 0, "tokens": 0}
        by_model[record.model_name]["requests"] += 1
        by_model[record.model_name]["tokens"] += record.total_tokens
    
    return {
        "total_tokens": total_tokens,
        "total_requests": total_requests,
        "by_model": by_model,
        "days": days
    }


@app.get("/usage/by-user")
async def get_usage_by_user(days: int = 7, db: Session = Depends(get_db)):
    """Get usage statistics by user"""
    cutoff = datetime.utcnow() - timedelta(days=days)
    rows = db.query(User.id, User.username, TokenUsage.total_tokens).join(
        APIKey, APIKey.user_id == User.id
    ).join(
        TokenUsage, TokenUsage.api_key_id == APIKey.id
    ).filter(TokenUsage.timestamp >= cutoff).all()

    summary: Dict[str, Dict[str, Any]] = {}
    for user_id, username, total_tokens in rows:
        key = str(user_id)
        if key not in summary:
            summary[key] = {"user_id": user_id, "username": username, "tokens": 0, "requests": 0}
        summary[key]["tokens"] += total_tokens
        summary[key]["requests"] += 1

    return {"days": days, "users": list(summary.values())}


@app.get("/usage/logs")
async def get_usage_logs(limit: int = 200, db: Session = Depends(get_db)):
    """Get recent usage logs with user info"""
    rows = db.query(
        TokenUsage,
        APIKey,
        User
    ).join(APIKey, APIKey.id == TokenUsage.api_key_id)
    rows = rows.join(User, User.id == APIKey.user_id)
    rows = rows.order_by(TokenUsage.timestamp.desc()).limit(limit).all()

    logs = []
    for usage, api_key, user in rows:
        logs.append({
            "id": usage.id,
            "timestamp": usage.timestamp.isoformat() if usage.timestamp else None,
            "username": user.username if user else None,
            "user_id": user.id if user else None,
            "api_key_name": api_key.name if api_key else None,
            "model": usage.model_name,
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
            "total_tokens": usage.total_tokens
        })

    return {"logs": logs}


def _extract_api_key(request: Request) -> Optional[str]:
    auth_header = request.headers.get("Authorization")
    api_key_header = request.headers.get("X-API-Key")
    if api_key_header:
        return api_key_header
    if auth_header:
        if auth_header.startswith("Bearer "):
            return auth_header[7:]
        return auth_header
    return None


@app.post("/proxy/chat/completions")
async def proxy_chat_completions(request: Request, db: Session = Depends(get_db)):
    """Proxy OpenAI chat completions to the resolved vLLM backend"""
    try:
        raw_body = await request.body()
    except ClientDisconnect:
        logger.info("/proxy/chat/completions client disconnected before body")
        return JSONResponse(status_code=499, content={"error": "Client disconnected"})

    if not raw_body:
        logger.info("/proxy/chat/completions empty body; headers=%s", dict(request.headers))
        raise HTTPException(status_code=400, detail="Empty request body")

    try:
        payload = json.loads(raw_body)
    except Exception:
        logger.info("/proxy/chat/completions invalid JSON; headers=%s", dict(request.headers))
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    logger.info("/proxy/chat/completions request: %s", json.dumps(payload, ensure_ascii=False))
    model = payload.get("model")
    if not model:
        raise HTTPException(status_code=400, detail="Missing model parameter")

    # Sanitize fields that can break vLLM/harmony parser
    allow_tools_env = os.getenv("ALLOW_TOOLS")
    allow_tools = True if allow_tools_env is None else allow_tools_env.lower() in {"1", "true", "yes"}
    blocked_keys = ["strict", "response_format"]
    if not allow_tools:
        blocked_keys += ["tools", "tool_choice", "functions", "function_call"]
    for key in blocked_keys:
        if key in payload:
            payload.pop(key, None)

    # Normalize max tokens: prefer explicit request, else apply a safe default
    if "max_tokens" not in payload and "max_output_tokens" in payload:
        payload["max_tokens"] = payload.get("max_output_tokens")
    if "max_tokens" not in payload and "max_completion_tokens" in payload:
        payload["max_tokens"] = payload.get("max_completion_tokens")
    if "max_output_tokens" in payload:
        payload.pop("max_output_tokens", None)
    if "max_completion_tokens" in payload:
        payload.pop("max_completion_tokens", None)
    original_max_tokens = payload.get("max_tokens")
    payload["max_tokens"] = _coerce_max_tokens(original_max_tokens, default=2048)
    if original_max_tokens != payload["max_tokens"]:
        logger.info(
            "/proxy/chat/completions normalized max_tokens from %r to %s",
            original_max_tokens,
            payload["max_tokens"],
        )

    api_key_value = _extract_api_key(request)
    if not api_key_value:
        raise HTTPException(status_code=401, detail="Missing API key")

    api_key = db.query(APIKey).filter(APIKey.key == api_key_value).first()
    if not api_key or not api_key.enabled:
        raise HTTPException(status_code=401, detail="Invalid API key")

    if api_key.user and not api_key.user.is_active:
        raise HTTPException(status_code=403, detail="User is disabled")

    resolved = await resolve_model(ResolveModelRequest(model=model), db)
    backend_url = resolved["backend_url"]

    if "messages" in payload:
        payload["messages"] = _messages_to_string(payload.get("messages"))

    max_model_len = _get_int_env_setting(["VLLM_MAX_MODEL_LEN", "MAX_MODEL_LEN", "MODEL_MAX_LEN"], 129000)
    chars_per_token_raw = os.getenv("TOKEN_CHARS_PER_TOKEN") or _read_env_file().get("TOKEN_CHARS_PER_TOKEN")
    try:
        chars_per_token = float(chars_per_token_raw) if chars_per_token_raw is not None else 4.0
    except Exception:
        chars_per_token = 4.0
    if chars_per_token <= 0:
        chars_per_token = 4.0
    prompt_tokens_est = _estimate_prompt_tokens(payload.get("messages"), chars_per_token)
    if prompt_tokens_est is not None:
        logger.info(
            "/proxy/chat/completions estimated prompt tokens: %s (chars_per_token=%s, max_model_len=%s)",
            prompt_tokens_est,
            chars_per_token,
            max_model_len,
        )
        available = max_model_len - prompt_tokens_est
        if available < 1:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Prompt too long for model context (estimated {prompt_tokens_est} tokens > "
                    f"max_model_len {max_model_len}). Reduce the system prompt or truncate messages."
                ),
            )
        if isinstance(payload.get("max_tokens"), int) and payload["max_tokens"] > available:
            original_max_tokens = payload["max_tokens"]
            payload["max_tokens"] = max(1, available)
            logger.info(
                "/proxy/chat/completions capped max_tokens from %s to %s based on est_prompt_tokens=%s and max_model_len=%s",
                original_max_tokens,
                payload["max_tokens"],
                prompt_tokens_est,
                max_model_len,
            )

    client_accept = request.headers.get("Accept", "")
    logger.info("/proxy/chat/completions accept: %s", client_accept)
    stream = bool(payload.get("stream"))
    force_stream_env = os.getenv("FORCE_STREAM")
    force_stream = True if force_stream_env is None else force_stream_env.lower() in {"1", "true", "yes"}
    if stream and "text/event-stream" not in client_accept and not force_stream:
        stream = False
        payload.pop("stream", None)
        logger.info("/proxy/chat/completions stream disabled (missing text/event-stream)")
    elif stream and "text/event-stream" not in client_accept and force_stream:
        logger.info("/proxy/chat/completions stream forced despite Accept header")
    if not stream and "stream_options" in payload:
        payload.pop("stream_options", None)
    if stream:
        logger.info("/proxy/chat/completions stream: enabled")
        payload["stream"] = True
        stream_options = _sanitize_stream_options(payload.get("stream_options"))
        if stream_options is None:
            payload.pop("stream_options", None)
        else:
            payload["stream_options"] = stream_options

        async def _iter_sse():
            usage_info = None
            tool_call_accumulators: Dict[int, Dict[str, Any]] = {}
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream(
                    "POST",
                    f"{backend_url}/v1/chat/completions",
                    json=payload,
                ) as resp:
                    if resp.status_code >= 400:
                        body = await resp.aread()
                        logger.info("/proxy/chat/completions upstream error: status=%s body=%s", resp.status_code, body.decode("utf-8", errors="ignore"))
                        yield ("data: " + json.dumps({"error": "Upstream error"}) + "\n\n").encode("utf-8")
                        yield b"data: [DONE]\n\n"
                        return

                    async for line in resp.aiter_lines():
                        if not line:
                            continue
                        if line.strip() == "data: [DONE]":
                            yield b"data: [DONE]\n\n"
                            continue
                        if not line.startswith("data: "):
                            continue
                        data_part = line[len("data: "):].strip()
                        try:
                            chunk = json.loads(data_part)
                        except Exception:
                            continue

                        if isinstance(chunk, dict) and chunk.get("usage"):
                            usage_info = chunk.get("usage")

                        choices = chunk.get("choices") if isinstance(chunk, dict) else None
                        if not isinstance(choices, list) or not choices:
                            if usage_info is not None:
                                out = {
                                    "id": chunk.get("id", f"chatcmpl-{secrets.token_hex(8)}"),
                                    "object": "chat.completion.chunk",
                                    "model": chunk.get("model", model),
                                    "choices": [],
                                    "usage": usage_info,
                                }
                                _validate_chat_chunk(out)
                                logger.info("/proxy/chat/completions stream out: %s", json.dumps(out, ensure_ascii=False))
                                yield ("data: " + json.dumps(out) + "\n\n").encode("utf-8")
                            continue

                        out = {
                            "id": chunk.get("id", f"chatcmpl-{secrets.token_hex(8)}"),
                            "object": "chat.completion.chunk",
                            "model": chunk.get("model", model),
                            "choices": []
                        }

                        for choice in choices:
                            if not isinstance(choice, dict):
                                continue
                            delta = choice.get("delta") or {}
                            content_blocks = _normalize_content_blocks(delta.get("content"))
                            content_text = "".join(
                                block.get("text", "")
                                for block in content_blocks
                                if isinstance(block, dict)
                            )
                            finish_reason = choice.get("finish_reason")
                            role = delta.get("role") if isinstance(delta, dict) else None
                            tool_calls = delta.get("tool_calls") if isinstance(delta, dict) else None
                            if tool_calls is not None:
                                _record_tool_call_debug("stream_chunk", chunk.get("model", model), tool_calls, raw=data_part)
                            tool_calls = _fix_tool_calls(tool_calls, allow_partial_args=True)
                            if tool_calls:
                                _accumulate_tool_calls(tool_call_accumulators, tool_calls)
                            has_content = bool(content_text and content_text.strip())
                            has_tool_calls = bool(tool_calls) or bool(tool_call_accumulators)
                            if not has_content and finish_reason is None and role is None and not has_tool_calls:
                                continue
                            out_choice = {
                                "index": choice.get("index", 0),
                                "delta": {}
                            }
                            if has_content:
                                out_choice["delta"]["content"] = content_text
                            if role:
                                out_choice["delta"]["role"] = role
                            if finish_reason == "tool_calls" and tool_call_accumulators:
                                finalized_tool_calls = _finalize_tool_call_accumulators(tool_call_accumulators)
                                tool_call_accumulators.clear()
                                if finalized_tool_calls and _validate_tool_calls(finalized_tool_calls, stage="stream_out", require_json_args=True):
                                    out_choice["delta"]["tool_calls"] = finalized_tool_calls
                                else:
                                    try:
                                        tool_call_fallback_counter.labels(stage="stream_out", action="drop_invalid").inc()
                                    except Exception:
                                        logger.exception("Failed to increment tool_call_fallback_counter")
                            if finish_reason is not None:
                                out_choice["finish_reason"] = finish_reason
                            if not out_choice["delta"] and out_choice.get("finish_reason") == "tool_calls":
                                continue
                            out["choices"].append(out_choice)

                        if out["choices"]:
                            _validate_chat_chunk(out)
                            logger.info("/proxy/chat/completions stream out: %s", json.dumps(out, ensure_ascii=False))
                            yield ("data: " + json.dumps(out) + "\n\n").encode("utf-8")

            if usage_info is not None:
                usage_record = TokenUsage(
                    api_key_id=api_key.id,
                    model_name=model,
                    prompt_tokens=usage_info.get("prompt_tokens", 0),
                    completion_tokens=usage_info.get("completion_tokens", 0),
                    total_tokens=usage_info.get("total_tokens", 0),
                )
                db.add(usage_record)
                db.commit()

        return StreamingResponse(_iter_sse(), media_type="text/event-stream")

    try:
        logger.info("/proxy/chat/completions non-stream upstream: POST %s", f"{backend_url}/v1/chat/completions")
        response = requests.post(
            f"{backend_url}/v1/chat/completions",
            json=payload,
            timeout=120
        )
    except requests.exceptions.RequestException as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    logger.info("/proxy/chat/completions non-stream upstream status: %s", response.status_code)

    try:
        data = response.json()
    except Exception:
        logger.info("/proxy/chat/completions upstream non-JSON response")
        return JSONResponse(status_code=response.status_code, content={"error": "Upstream error"})

    # Record usage if present
    usage = data.get("usage") or {}
    usage_record = TokenUsage(
        api_key_id=api_key.id,
        model_name=model,
        prompt_tokens=usage.get("prompt_tokens", 0),
        completion_tokens=usage.get("completion_tokens", 0),
        total_tokens=usage.get("total_tokens", 0)
    )
    db.add(usage_record)
    db.commit()

    # Strict, minimal OpenAI-compatible response
    message = None
    choices = data.get("choices") if isinstance(data, dict) else None
    if isinstance(choices, list) and choices:
        message = choices[0].get("message")
    content_blocks = _normalize_content_blocks(message.get("content") if isinstance(message, dict) else None)
    content_text = "".join(
        block.get("text", "")
        for block in content_blocks
        if isinstance(block, dict)
    )
    tool_calls = message.get("tool_calls") if isinstance(message, dict) else None
    if tool_calls is not None:
        _record_tool_call_debug("non_stream_response", data.get("model", model), tool_calls)
    tool_calls = _fix_tool_calls(tool_calls)
    if tool_calls and not _validate_tool_calls(tool_calls, stage="non_stream_out", require_json_args=True):
        try:
            tool_call_fallback_counter.labels(stage="non_stream_out", action="drop_invalid").inc()
        except Exception:
            logger.exception("Failed to increment tool_call_fallback_counter")
        tool_calls = None

    strict_response = {
        "id": data.get("id", "chatcmpl-"),
        "object": "chat.completion",
        "created": data.get("created"),
        "model": data.get("model", model),
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content_text},
                "finish_reason": (choices[0].get("finish_reason") if isinstance(choices, list) and choices else None) or "stop"
            }
        ],
        "usage": {
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0)
        }
    }

    if tool_calls:
        strict_response["choices"][0]["message"]["tool_calls"] = tool_calls
    _validate_chat_response(strict_response)
    logger.info("/proxy/chat/completions response: %s", json.dumps(strict_response, ensure_ascii=False))
    return JSONResponse(status_code=response.status_code, content=strict_response)


@app.post("/proxy/responses")
async def proxy_responses(request: Request, db: Session = Depends(get_db)):
    """Proxy OpenAI responses to chat completions and normalize output"""
    try:
        raw_body = await request.body()
    except ClientDisconnect:
        logger.info("/proxy/responses client disconnected before body")
        return JSONResponse(status_code=499, content={"error": "Client disconnected"})

    if not raw_body:
        logger.info("/proxy/responses empty body; headers=%s", dict(request.headers))
        raise HTTPException(status_code=400, detail="Empty request body")

    try:
        payload = json.loads(raw_body)
    except Exception:
        logger.info("/proxy/responses invalid JSON; headers=%s", dict(request.headers))
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    logger.info("/proxy/responses request: %s", json.dumps(payload, ensure_ascii=False))
    model = payload.get("model")
    if not model:
        raise HTTPException(status_code=400, detail="Missing model parameter")

    api_key_value = _extract_api_key(request)
    if not api_key_value:
        raise HTTPException(status_code=401, detail="Missing API key")

    api_key = db.query(APIKey).filter(APIKey.key == api_key_value).first()
    if not api_key or not api_key.enabled:
        raise HTTPException(status_code=401, detail="Invalid API key")

    if api_key.user and not api_key.user.is_active:
        raise HTTPException(status_code=403, detail="User is disabled")

    client_accept = request.headers.get("accept", "")
    stream = bool(payload.get("stream"))
    force_stream_env = os.getenv("FORCE_STREAM")
    force_stream = True if force_stream_env is None else force_stream_env.lower() in {"1", "true", "yes"}
    if stream and "text/event-stream" not in client_accept and not force_stream:
        stream = False
        payload.pop("stream", None)

    # Convert responses input to chat messages
    input_text = payload.get("input")
    messages = payload.get("messages")
    if not messages:
        if isinstance(input_text, str):
            messages = [{"role": "user", "content": input_text}]
        else:
            messages = [{"role": "user", "content": ""}]

    messages = _messages_to_string(messages)

    raw_max_tokens = payload.get("max_output_tokens") or payload.get("max_tokens")
    chat_payload = {
        "model": model,
        "messages": messages,
        "max_tokens": _coerce_max_tokens(raw_max_tokens, default=2048),
        "stream": stream,
    }
    if raw_max_tokens != chat_payload["max_tokens"]:
        logger.info(
            "/proxy/responses normalized max_tokens from %r to %s",
            raw_max_tokens,
            chat_payload["max_tokens"],
        )

    resolved = await resolve_model(ResolveModelRequest(model=model), db)
    backend_url = resolved["backend_url"]

    try:
        response = requests.post(
            f"{backend_url}/v1/chat/completions",
            json=chat_payload,
            timeout=120,
            stream=stream
        )
    except requests.exceptions.RequestException as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    if stream:
        logger.info("/proxy/responses stream: enabled")
        response = requests.post(
            f"{backend_url}/v1/chat/completions",
            json={**chat_payload, "stream": False},
            timeout=120
        )

        def _iter_responses_sse():
            try:
                data = response.json()
            except Exception:
                yield b"data: {\"type\":\"response.completed\"}\n\n"
                return

            text = ""
            choices = data.get("choices") if isinstance(data, dict) else None
            if isinstance(choices, list) and choices:
                msg = choices[0].get("message") or {}
                content = msg.get("content")
                if isinstance(content, list) and content:
                    text = content[0].get("text") or ""
                elif isinstance(content, str):
                    text = content

            if text:
                payload = {"type": "response.output_text.delta", "delta": text}
                yield ("data: " + json.dumps(payload) + "\n\n").encode("utf-8")
            yield b"data: {\"type\":\"response.completed\"}\n\n"

        return StreamingResponse(_iter_responses_sse(), media_type="text/event-stream")

    data = response.json()
    text = ""
    choices = data.get("choices") if isinstance(data, dict) else None
    if isinstance(choices, list) and choices:
        msg = choices[0].get("message") or {}
        content = msg.get("content")
        if isinstance(content, list) and content:
            text = content[0].get("text") or ""
        elif isinstance(content, str):
            text = content

    usage = data.get("usage") or {}
    usage_record = TokenUsage(
        api_key_id=api_key.id,
        model_name=model,
        prompt_tokens=usage.get("prompt_tokens", 0),
        completion_tokens=usage.get("completion_tokens", 0),
        total_tokens=usage.get("total_tokens", 0)
    )
    db.add(usage_record)
    db.commit()

    response_obj = {
        "id": data.get("id", "resp-"),
        "object": "response",
        "created": data.get("created"),
        "model": model,
        "output": [
            {
                "id": "msg-1",
                "type": "message",
                "role": "assistant",
                "content": [
                    {"type": "output_text", "text": text}
                ]
            }
        ],
        "usage": {
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0)
        }
    }
    logger.info("/proxy/responses response: %s", json.dumps(response_obj, ensure_ascii=False))
    return JSONResponse(status_code=response.status_code, content=response_obj)


@app.get("/proxy/models")
async def proxy_models(db: Session = Depends(get_db)):
    """Return registered models in OpenAI-compatible format"""
    models = db.query(Model).filter(Model.enabled == True).all()
    expose_tools_env = os.getenv("EXPOSE_TOOLS", "true")
    expose_tools = expose_tools_env.lower() in {"1", "true", "yes"}
    available_tools = [
        {
            "type": "function",
            "function": {
                "name": "search_files",
                "description": "Search files by content pattern",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Directory path"},
                        "regex": {"type": "string", "description": "Search regex pattern"},
                        "file_pattern": {"type": "string", "description": "File pattern"},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_files",
                "description": "List files in a directory",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Directory path"},
                        "recursive": {"type": "boolean", "description": "Recursive listing"},
                    },
                },
            },
        },
    ]
    return {
        "object": "list",
        "data": [
            {
                "id": m.name,
                "object": "model",
                "owned_by": "vllm-platform",
                "created": int(m.created_at.timestamp()) if m.created_at else None,
                "capabilities": {
                    "tool_calls": True,
                    "function_calling": True,
                },
                "available_tools": available_tools if expose_tools else None,
            }
            for m in models
        ]
    }


@app.get("/proxy/debug/tool-calls")
async def proxy_debug_tool_calls(request: Request, limit: int = 50, clear: bool = False):
    """Return recent raw backend tool-call chunks for debugging."""
    _require_admin_key(request)
    safe_limit = max(1, min(limit, TOOL_CALL_DEBUG_MAX))
    items = list(TOOL_CALL_DEBUG_BUFFER)[-safe_limit:]
    if clear:
        TOOL_CALL_DEBUG_BUFFER.clear()
    return {"count": len(items), "items": items}


# Metrics endpoint for Prometheus
@app.get("/metrics")
async def metrics():
    """Prometheus metrics"""
    return generate_latest(), 200, {'Content-Type': CONTENT_TYPE_LATEST}


@app.get("/ops/status")
async def ops_status():
    """Get platform status output"""
    return _run_script("status.sh")


@app.post("/ops/deploy")
async def ops_deploy():
    """Start/Deploy gateway stack"""
    return _run_script("deploy.sh")


@app.post("/ops/stop")
async def ops_stop():
    """Stop gateway stack"""
    return _run_script("stop.sh")


@app.post("/ops/reset")
async def ops_reset():
    """Cold start reset: stop + remove containers/volumes"""
    return _run_script("reset.sh")


@app.get("/ops/env")
async def ops_get_env():
    """Get current environment values"""
    return {"values": _read_env_file()}


@app.put("/ops/env")
async def ops_update_env(payload: EnvUpdateRequest):
    """Update environment values"""
    _write_env_file(payload.values)
    return {"ok": True, "values": _read_env_file()}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
