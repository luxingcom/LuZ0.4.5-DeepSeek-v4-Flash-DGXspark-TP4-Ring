# -*- coding: utf-8 -*-
"""
DeepSeek Responses API Gateway for vLLM — v2.0-slim (pure external entry)
=========================================================================
Thin FastAPI proxy: client auth + model alias + routing + reasoning mirror.
All traffic governance (concurrency / TTFT budget / heartbeat / dedup /
slow-client protection) lives in the concurrency-proxy v2 (rc3.6, 8001) on
node01; thinking-mode default injection lives there too (S2, env switch).

  - POST /v1/responses        : auth -> model alias (strict 404) -> strip
                                reasoning_effort -> proxy to vLLM 8001
                                (non-stream JSON / stream SSE passthrough)
  - POST /v1/chat/completions : auth -> model alias (strict 404) -> proxy.
                                SSE lines get `reasoning` mirrored to
                                `reasoning_content` (vLLM -> DeepSeek compat).
  - POST /v1/embeddings       : transparent proxy to EMBED_URL (Qwen3-Embedding)
  - GET  /v1/models           : expose alias model names (PUBLIC + LEGACY)
  - GET  /health              : liveness probe

Each POST route is mounted under both `/v1/<path>` and `/<path>`.

v2.0-slim (code-reviewer, 2026-09-07, S3 of ADR-8003-slim):
  DELETED (0-dependency, evidence: gateway.log profile 8/26-9/7 + golden
  baseline G3/G4):
  - _inject_enable_thinking() + both call sites + FORCE_ENABLE_THINKING env.
    Profile: enable_thinking explicitly passed 0 times in 58,969 accesses;
    golden G3/G4 prove the engine's default thinking behavior is already on,
    so removal keeps the default response shape unchanged. Belt-and-braces:
    8001 rc3.6 has INJECT_ENABLE_THINKING (default off) if a default-ever
    needs to be forced centrally.
  - UPSTREAM_API_KEY injection (3 sites). ADR fact F7: 8001/8002/8022 are
    all unauthenticated today, so the injected header was verified by no one
    (dead code). Client Authorization is still dropped (_DROP_HEADERS);
    nothing is injected upstream. Env read retained as a switch slot for the
    day an upstream gains auth (search UPSTREAM_API_KEY below).
  Kept byte-for-byte behavior-wise: auth (incl. 401 body), strict model 404,
  reasoning_effort strip on /v1/responses, reasoning mirroring (non-stream +
  SSE line level) on chat, SSE passthrough on responses, model aliasing,
  /health, quirky passthroughs (empty messages 200, created=0, embeddings
  502 type=upstream_error) — golden AC-1..AC-10 must diff clean.

v1.5.0 (code-reviewer, 2026-08-05): reasoning chain fix — _inject_enable_
thinking() + reasoning->reasoning_content mirroring (chat route, non-stream
JSON + SSE line level). [injection part removed in v2.0-slim; mirror kept]
v1.4.0 (sre-engineer, 2026-08-04): +/v1/chat/completions strict-alias route;
stopped stripping `reasoning` on /v1/responses; 502 type standardized to
api_error (embeddings route kept upstream_error).
v1.3.0 (sre-engineer, 2026-08-04): public model renamed to local-v4-flash;
deepseek-v4-flash kept as LEGACY_MODEL alias.
v1.2.0 (sre-engineer, 2026-08-03): +/v1/embeddings transparent proxy.

Deployed on node02:8003, forwarding to VLLM_URL (node01 concurrency
gateway).
"""

import json
import os
import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("responses-gateway")

VLLM_URL = os.environ.get("VLLM_URL", "http://_PH_HEAD_IP_.186:8001")
EMBED_URL = os.environ.get("EMBED_URL", "http://_PH_HEAD_IP_.188:8022")
API_KEY = os.environ.get("API_KEY", "").strip()
# v2.0-slim: switch slot only. Upstreams (8001/8002/8022) are unauthenticated
# today (ADR F7), so nothing is injected. If an upstream enables auth later,
# re-add `headers["Authorization"] = f"Bearer {UPSTREAM_API_KEY}"` at the
# three proxy sites marked INJECT-POINT.
UPSTREAM_API_KEY = os.environ.get("UPSTREAM_API_KEY", "").strip()
SERVED_MODEL = os.environ.get("SERVED_MODEL", "deepseek-v4-flash-0731")
PUBLIC_MODEL = os.environ.get("PUBLIC_MODEL", "local-v4-flash")
# Compatibility alias for the old public model name. Kept so that existing
# clients using `deepseek-v4-flash` continue to work; maps to SERVED_MODEL
# exactly like PUBLIC_MODEL.
LEGACY_MODEL = os.environ.get("LEGACY_MODEL", "deepseek-v4-flash")

# Long-lived async client: MUST NOT be scoped inside a request handler with
# `async with`, because StreamingResponse bodies are iterated lazily by the
# ASGI server AFTER the handler returns -- closing the client in the handler
# would sever the upstream stream and raise httpx.ReadError.
_client: httpx.AsyncClient | None = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    global _client
    _client = httpx.AsyncClient(timeout=None, follow_redirects=False)
    logger.info("upstream client ready: %s", VLLM_URL)
    try:
        yield
    finally:
        await _client.aclose()
        _client = None


app = FastAPI(title="DeepSeek Responses API Gateway", version="2.0.0", lifespan=lifespan)


def _upstream() -> httpx.AsyncClient:
    if _client is None:
        raise RuntimeError("upstream client not initialized")
    return _client

# model alias map: public name(s) -> vLLM served-name
MODEL_ALIAS = {
    PUBLIC_MODEL: SERVED_MODEL,
    LEGACY_MODEL: SERVED_MODEL,
    SERVED_MODEL: SERVED_MODEL,
}

# headers not forwarded upstream (client Authorization is dropped here; no
# upstream key is injected in v2.0-slim — see UPSTREAM_API_KEY note above)
_DROP_HEADERS = {"authorization", "host", "content-length", "connection", "accept-encoding"}


async def _check_auth(request: Request) -> bool:
    if not API_KEY:
        return True  # if no key configured, do not enforce (safety off)
    auth = request.headers.get("Authorization", "")
    return auth == f"Bearer {API_KEY}"


def _unauthorized() -> dict:
    return {
        "error": {
            "message": "Invalid API key provided",
            "type": "authentication_error",
            "code": "invalid_api_key",
        }
    }


def _model_not_found(model) -> dict:
    return {
        "error": {
            "message": f"The model '{model}' does not exist",
            "type": "invalid_request_error",
            "param": "model",
            "code": "model_not_found",
        }
    }


# --- reasoning -> reasoning_content field mirroring (vLLM compat shim) ---
# vLLM 0.25.2.dev0 emits the thinking text inside message.reasoning (and
# message.delta.reasoning in streams), while DeepSeek's official API and
# WorkBuddy's folding UI read message.reasoning_content. We MIRROR the value to
# reasoning_content and KEEP the original reasoning key (non-destructive): a
# client that reads either convention gets the thinking text, and
# OpenAI-compatible parsers ignore unknown fields, so the extra key is safe.
def _mirror_reasoning_fields(data: dict) -> None:
    if not isinstance(data, dict):
        return
    for choice in data.get("choices") or []:
        if not isinstance(choice, dict):
            continue
        # non-stream uses message, stream uses delta (some final chunks carry message)
        for target in (choice.get("message"), choice.get("delta")):
            if isinstance(target, dict) and target.get("reasoning") is not None:
                target["reasoning_content"] = target["reasoning"]


def _rewrite_sse_line(line: bytes) -> bytes:
    """Rewrite one SSE line: mirror reasoning -> reasoning_content.

    Lines without a `data: ` prefix (keep-alives/comments) and the terminal
    `data: [DONE]` are passed through untouched. Unparseable payloads are also
    passed through untouched so an upstream hiccup never breaks the stream.
    """
    prefix = b"data: "
    if not line.startswith(prefix):
        return line
    payload = line[len(prefix):]
    if payload.strip() == b"[DONE]":
        return line
    try:
        data = json.loads(payload)
    except (ValueError, TypeError):
        return line
    if isinstance(data, dict):
        _mirror_reasoning_fields(data)
        return prefix + json.dumps(data).encode("utf-8")
    return line


@app.get("/health")
async def health():
    return {"status": "ok", "service": "responses-gateway", "backend": VLLM_URL, "embedding": EMBED_URL}


# openai SDK uses `/responses` when base_url ends WITHOUT /v1 (e.g.
# base_url="http://host:8003"), and `/v1/responses` when base_url ends WITH /v1.
# Mount both forms for maximum client compatibility.
@app.get("/models")
@app.get("/v1/models")
async def list_models(request: Request):
    if not await _check_auth(request):
        return JSONResponse(status_code=401, content=_unauthorized())
    now = 0
    data = [
        {"id": PUBLIC_MODEL, "object": "model", "created": now, "owned_by": "deepseek"},
        {"id": SERVED_MODEL, "object": "model", "created": now, "owned_by": "deepseek"},
    ]
    if LEGACY_MODEL != PUBLIC_MODEL and LEGACY_MODEL != SERVED_MODEL:
        data.append({"id": LEGACY_MODEL, "object": "model", "created": now, "owned_by": "deepseek"})
    return {
        "object": "list",
        "data": data,
    }


@app.post("/embeddings")
@app.post("/v1/embeddings")
async def create_embeddings(request: Request):
    if not await _check_auth(request):
        return JSONResponse(status_code=401, content=_unauthorized())

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": {"message": "Invalid JSON body", "type": "invalid_request_error"}})

    headers = {k: v for k, v in request.headers.items() if k.lower() not in _DROP_HEADERS and k.lower() != "content-type"}
    headers["Content-Type"] = "application/json"   # 单次设置（Starlette headers 键为小写，setdefault 会叠加重复头）
    # INJECT-POINT (embeddings): see UPSTREAM_API_KEY note (nothing injected).

    upstream_url = f"{EMBED_URL}/v1/embeddings"

    client = _upstream()
    req = client.build_request("POST", upstream_url, json=body, headers=headers)
    try:
        resp = await client.send(req)
    except httpx.HTTPError as e:
        logger.error("embedding upstream error: %s", e)
        return JSONResponse(status_code=502, content={"error": {"message": f"Upstream embedding backend error: {e}", "type": "upstream_error"}})

    content = await resp.aread()
    await resp.aclose()
    return Response(content=content, status_code=resp.status_code, media_type=resp.headers.get("content-type", "application/json"))


@app.post("/responses")
@app.post("/v1/responses")
async def create_response(request: Request):
    if not await _check_auth(request):
        return JSONResponse(status_code=401, content=_unauthorized())

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": {"message": "Invalid JSON body", "type": "invalid_request_error"}})

    # --- model alias mapping ---
    model = body.get("model")
    if model not in MODEL_ALIAS:
        return JSONResponse(status_code=404, content=_model_not_found(model))
    body["model"] = MODEL_ALIAS[model]

    # --- strip unsupported / incompatible fields (DeepSeek semantics: silently ignore) ---
    # vLLM native `reasoning.effort` rejects 'max'; our backend is pinned to
    # thinking=max via chat template, so drop the field and let vLLM default apply.
    # NOTE: `reasoning` field is intentionally passed through to vLLM so the
    # upstream can handle it natively (vLLM 0.x responses schema supports it).
    # extra DeepSeek fields that vLLM native responses schema rejects
    for f in ("reasoning_effort",):
        body.pop(f, None)
    # v2.0-slim: _inject_enable_thinking() removed (profile 0 use + golden
    # G3/G4 prove engine default already emits reasoning; central default, if
    # ever needed, lives in 8001 rc3.6 INJECT_ENABLE_THINKING).

    headers = {k: v for k, v in request.headers.items() if k.lower() not in _DROP_HEADERS and k.lower() != "content-type"}
    headers["Content-Type"] = "application/json"   # 单次设置（Starlette headers 键为小写，setdefault 会叠加重复头）
    # INJECT-POINT (responses): see UPSTREAM_API_KEY note (nothing injected).

    upstream_url = f"{VLLM_URL}/v1/responses"
    is_stream = bool(body.get("stream", False))

    client = _upstream()
    req = client.build_request("POST", upstream_url, json=body, headers=headers)
    try:
        resp = await client.send(req, stream=is_stream)
    except httpx.HTTPError as e:
        logger.error("upstream error: %s", e)
        return JSONResponse(status_code=502, content={"error": {"message": f"Upstream backend error: {e}", "type": "api_error"}})

    ctype = resp.headers.get("content-type", "text/event-stream" if is_stream else "application/json")

    if is_stream:
        async def gen():
            try:
                async for chunk in resp.aiter_bytes():
                    yield chunk
            except httpx.HTTPError as e:
                logger.warning("upstream stream interrupted: %s", e)
            finally:
                await resp.aclose()
        return StreamingResponse(
            gen(),
            status_code=resp.status_code,
            media_type=ctype,
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    else:
        content = await resp.aread()
        await resp.aclose()
        return Response(content=content, status_code=resp.status_code, media_type=ctype)


@app.post("/chat/completions")
@app.post("/v1/chat/completions")
async def create_chat_completion(request: Request):
    """Traditional OpenAI chat completions passthrough.

    WorkBuddy (and any openai-compatible client using /v1/chat/completions)
    hits this route. Auth + model alias mirror /v1/responses; the body
    (messages/temperature/max_tokens/top_p/...) is forwarded as-is because
    vLLM 8001 natively implements /v1/chat/completions. Model validation is
    STRICT: only known aliases are accepted (unknown -> 404). Streaming
    (stream=true) rewrites SSE lines so `reasoning` is mirrored to
    `reasoning_content` (see _rewrite_sse_line), preserving the standard
    OpenAI chat stream format including the terminal `data: [DONE]`.
    """
    if not await _check_auth(request):
        return JSONResponse(status_code=401, content=_unauthorized())

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": {"message": "Invalid JSON body", "type": "invalid_request_error"}})

    # --- model alias mapping (strict: unknown -> 404) ---
    model = body.get("model")
    if model not in MODEL_ALIAS:
        return JSONResponse(status_code=404, content=_model_not_found(model))
    body["model"] = MODEL_ALIAS[model]
    # v2.0-slim: _inject_enable_thinking() removed (see /v1/responses note).

    headers = {k: v for k, v in request.headers.items() if k.lower() not in _DROP_HEADERS and k.lower() != "content-type"}
    headers["Content-Type"] = "application/json"   # 单次设置（Starlette headers 键为小写，setdefault 会叠加重复头）
    # INJECT-POINT (chat): see UPSTREAM_API_KEY note (nothing injected).

    upstream_url = f"{VLLM_URL}/v1/chat/completions"
    is_stream = bool(body.get("stream", False))

    client = _upstream()
    req = client.build_request("POST", upstream_url, json=body, headers=headers)
    try:
        resp = await client.send(req, stream=is_stream)
    except httpx.HTTPError as e:
        logger.error("chat upstream error: %s", e)
        return JSONResponse(status_code=502, content={"error": {"message": f"Upstream backend error: {e}", "type": "api_error"}})

    ctype = resp.headers.get("content-type", "text/event-stream" if is_stream else "application/json")

    if is_stream:
        async def gen():
            # SSE line-buffered transformer: each `data: {...}` line has its
            # `reasoning` mirrored to `reasoning_content`. Bytes are buffered
            # across chunks so a JSON line split at a chunk boundary is still
            # parsed as one unit; SSE framing (`data: ` prefix, `\n` line
            # terminator, blank-line event separators, `data: [DONE]`) is
            # preserved byte-for-byte.
            buf = b""
            try:
                async for chunk in resp.aiter_bytes():
                    buf += chunk
                    lines = buf.split(b"\n")
                    buf = lines.pop()  # trailing partial line (may be empty)
                    for line in lines:
                        yield _rewrite_sse_line(line) + b"\n"
                if buf:
                    yield _rewrite_sse_line(buf)
            except httpx.HTTPError as e:
                logger.warning("chat upstream stream interrupted: %s", e)
            finally:
                await resp.aclose()
        return StreamingResponse(
            gen(),
            status_code=resp.status_code,
            media_type=ctype,
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    else:
        content = await resp.aread()
        await resp.aclose()
        # Mirror vLLM `reasoning` -> DeepSeek-compatible `reasoning_content`
        # (non-stream JSON). If the payload is not JSON (e.g. upstream error),
        # pass the original bytes through untouched.
        try:
            data = json.loads(content)
        except (ValueError, TypeError):
            data = None
        if isinstance(data, dict):
            _mirror_reasoning_fields(data)
            content = json.dumps(data).encode("utf-8")
        return Response(content=content, status_code=resp.status_code, media_type=ctype)


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("GATEWAY_PORT", "8003"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
