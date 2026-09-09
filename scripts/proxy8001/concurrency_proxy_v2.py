#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
concurrency_proxy_v2.py — vLLM 流式感知并发网关（v2.0-rc3，2026-09-06）

背景（qwenpaw-internal-error-rca-external-luz045-2026-09-06.md + gateway 专项）：
  长上下文请求 prefill 分钟级 → 下游应用 30s 内容超时误杀 → 重试重新全量 prefill →
  失败风暴。v1 代理（8001→8002，MAX_CONCURRENCY=6）只做并发计数，长 prefill 场景"哑管"。

rc3.6.1 相对 rc3.6：注入路径扩展覆盖 /v1/responses（对齐旧 8003 双注入点——
  金样本实证注入是 reasoning 链源头开关，引擎端无缺省思考链）；
rc3.6 相对 rc3.5.1 的修正（S2：8003 功能下沉，督导批准，尽调结论落地）：
  enable_thinking 注入（原 8003 _inject_enable_thinking）：POST chat 路径 body
    缺省时注入 chat_template_kwargs.enable_thinking=true。默认 off
    （INJECT_ENABLE_THINKING=0 = 现行为零变化）。字节豁免优先（显式管理不
    覆盖不 parse），确定性变换在 body_key 前执行——去重键对注入后 body 计算且
    跨开关各自稳定；非法 JSON 原样返回走原逻辑。

rc3.5.1 相对 rc3.5 的修正（T21 三断言暴露的 P1：取消传播下 finally 清理跳过）：
  P1 CancelledError 在已取消协程内传播时，finally 的 await wait_for(write_eof)
    立即再抛 CancelledError（BaseException，except Exception 捕不住）→ 排在其
    后的 INFLIGHT.pop/active-=1 全部跳过（active 永久漂移+1；DEDUP=on 时键
    泄漏→同 payload 永久 429）。修复：finally 清理顺序反转（同步清理先行，
    write_eof 最后且吞取消），兜底分支同步此修法。

rc3.5 相对 rc3.4 的修正（终审 P0-B：WRITE_TIMEOUT 切流后信号量槽永久泄漏）：
  P0-B finally 的 write_eof 无超时包裹——其内部 drain 不受 WRITE_TIMEOUT 约束，
    慢读客户端在切流后仍不读 → eof drain 永久阻塞 → finally 卡死 →
    dispatch 的 SEM.release 永不执行（实测：6 个慢客户端耗尽 6 槽全站 429
    直至重启）。修复：两处 write_eof（finally + 兜底分支）均包
    wait_for(WRITE_TIMEOUT)，超时放弃 + resp.force_close()（防 aiohttp
    handler 返回后的内部 finish 路径再次 drain 同面阻塞）。

rc3.4 相对 rc3.3 的修正（多角度复审：精简/效率/安全/性能）：
  A 慢客户端静默截断（pump put_nowait 遇队列满丢数据帧，客户端 200+部分
    chunks+正常 EOF 无错误帧）→ 背压化：await q.put（put 与 readany 的
    CHUNK_IDLE 超时分捕获），数据帧零丢弃，等价 v1 直通/TCP 背压语义。
  B is_stream 每请求全量 json.loads（数 MB body 数 ms~数十 ms CPU）→
    "stream" 键字节串 prefilter，无键请求全免解析（语义零变化）。
  F GW_API_KEY 明文 == 比较（时序侧信道）→ hmac.compare_digest。

rc3.3 相对 rc3.2 的修正（终审 🟠×2 + 影子实例实测 P0×1）：
  P0 心跳未实时下发（node01 影子 76K token 实测：TTFT 12.5s 心跳积压同批）→
      消费循环并行化：producer（建连+首字节+泵送）/ consumer（客户端写循环）
      与 resp.prepare 后立即并行运行，长 prefill 期间心跳即写即达；
      TTFT 预算改由 first_seen 事件监管（超时取消 producer，其 finally 保证
      DONE 入队）；本地 T1 用例因走超时分支未覆盖此路径（已补 T19）。
  O-1 TTFT 预算两段串行最坏 2×（connect 段 + first readany 段各用满 600s）→
      first readany 共享 deadline（FIRST_TOKEN_TIMEOUT - 已耗时），总 TTFT 预算
      硬上限 = FIRST_TOKEN_TIMEOUT。
  O-2 unit 中"StartLimit 停转由 vllm 自愈链监控发现"为虚假声明（自愈链只探
      8002）→ unit 注释改真实描述，runbook 补首日人工值守步骤。

rc3 相对 rc2 的修正（三路交叉评审合并：并发/安全/SSE 兼容 + 人工复审）：
  P0-1 慢读客户端无保护 → 新增 WRITE_TIMEOUT（单次写客户端超时）与
       TOTAL_STREAM_TIMEOUT（整流总时长上限），超限断连并全量清理，
       根除"心跳假活 + 信号量槽耗尽"的 DoS 面。
  P0-2 管理端点零鉴权 → GW_API_KEY（未设则不鉴权，兼容内网 v1 形态；设置后
       /gw/* 需 Bearer）。业务路径不代理鉴权（上游 VLLM_API_KEY 负责）。
  P1-1 connect 阶段 TTFT 超时未捕获（wait_for 抛 TimeoutError 穿透早开流）→
       outcome 显式四分支（正常/连接失败/上游拒绝/超时），全部走错误帧+[DONE] 收尾，
       不再向外抛异常。
  P1-2 去重 TOCTOU（检查与登记隔 await prepare）→ INFLIGHT 原子占位（单线程
       事件循环内 check+set 无 await 间隙，天然原子；占位提前到 prepare 之前）。
  P1-3 错误帧信息泄露（拼入上游异常/响应体）→ 固定文案，细节仅入日志。
  P1-4 错误帧后无终止符（OpenAI SDK 挂等）→ 错误帧后追加 data: [DONE]。
  P1-5 is_stream 类型严格化：仅 isinstance(stream, bool) 且 True 才走流式。
  P1-6 client_max_size 512MB→64MB（600K token JSON 实测仅数 MB；防 3GB 峰值）。
  P1-7 去重 Retry-After 15→120s（原值诱导 429 重试风暴）。
  P2   URL 重组改 request.raw_path（防 #/% 解码错位）；移除 Host 硬编码（由
       aiohttp 按 URL 生成）；CookieJar→Dummy（不跨客户端回带 Cookie）；
       relay_plain 按原 method 转发（不再全转 POST）；X-Forwarded-For 追加；
       rejected_429_queue 双计数修复；metrics 增 uptime/版本/queue_now。

rc2 相对 rc1 的修正：心跳提前到转发后立即开始（早开流）；信号量生命周期收敛
dispatch 单点；authorization 头透传恢复；GET/HEAD 原样转发。

功能（G1~G6）：G1 SSE 心跳（HEARTBEAT_INTERVAL，`: keepalive` 注释帧）
  G2 TTFT 预算（FIRST_TOKEN_TIMEOUT）+ 流空闲超时（CHUNK_IDLE_TIMEOUT）
  G3 admission 反压（QUEUE_TIMEOUT → 429+Retry-After）
  G4 等值重试抑制（body sha256 在飞去重 → 429）
  G5 客户端断连传播（cancel 上游）  G6 观测（/gw/metrics）

部署：与 v1 同形（8001→8002）。systemd unit 见 concurrency-proxy-v2.service。
环境变量（默认值）：
  UPSTREAM=http://127.0.0.1:8002  PORT=8001  MAX_CONCURRENCY=6
  QUEUE_TIMEOUT=20   FIRST_TOKEN_TIMEOUT=600   CHUNK_IDLE_TIMEOUT=180
  HEARTBEAT_INTERVAL=5   RETRY_CONNECT=1   NONSTREAM_TOTAL_TIMEOUT=900
  WRITE_TIMEOUT=60   TOTAL_STREAM_TIMEOUT=7200   DEDUP_ENABLE=1   GW_API_KEY=
  INJECT_ENABLE_THINKING=0
"""
import asyncio
import hashlib
import hmac
import json
import logging
import os
import time

from aiohttp import ClientSession, ClientTimeout, DummyCookieJar, web

# ---------------------------------------------------------------- 配置
UPSTREAM = os.environ.get("UPSTREAM", "http://127.0.0.1:8002").rstrip("/")
PORT = int(os.environ.get("PORT", "8001"))
MAX_CONCURRENCY = int(os.environ.get("MAX_CONCURRENCY", "6"))
QUEUE_TIMEOUT = float(os.environ.get("QUEUE_TIMEOUT", "20"))
FIRST_TOKEN_TIMEOUT = float(os.environ.get("FIRST_TOKEN_TIMEOUT", "600"))
CHUNK_IDLE_TIMEOUT = float(os.environ.get("CHUNK_IDLE_TIMEOUT", "180"))
HEARTBEAT_INTERVAL = float(os.environ.get("HEARTBEAT_INTERVAL", "5"))
RETRY_CONNECT = int(os.environ.get("RETRY_CONNECT", "1"))
NONSTREAM_TOTAL_TIMEOUT = float(os.environ.get("NONSTREAM_TOTAL_TIMEOUT", "900"))
WRITE_TIMEOUT = float(os.environ.get("WRITE_TIMEOUT", "60"))
TOTAL_STREAM_TIMEOUT = float(os.environ.get("TOTAL_STREAM_TIMEOUT", "7200"))
DEDUP_ENABLE = os.environ.get("DEDUP_ENABLE", "1") == "1"
GW_API_KEY = os.environ.get("GW_API_KEY", "")
# S2 注入下沉（rc3.6）：默认 off——off = 现行为零变化
INJECT_ENABLE_THINKING = os.environ.get("INJECT_ENABLE_THINKING", "0") == "1"
VERSION = "concurrency-proxy-v2-rc3.6.1"

HEARTBEAT = b": keepalive\n\n"          # SSE 注释帧：OpenAI SDK/EventSource 忽略
DONE_MARK = b"data: [DONE]\n\n"         # 错误帧后的终止符（SDK 正常收尾）
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s gwv2 %(message)s",
)
log = logging.getLogger("gwv2")

# ---------------------------------------------------------------- 状态
SEM: asyncio.Semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
INFLIGHT: dict[str, float] = {}          # body_sha256 -> 占位时刻（原子占位）
STARTED_AT = time.time()
METRICS = {
    "version": VERSION, "uptime_sec": 0,
    "requests_total": 0, "streams_total": 0,
    "rejected_429_queue": 0, "rejected_429_duplicate": 0,
    "first_token_timeouts": 0, "chunk_idle_timeouts": 0,
    "write_timeouts": 0, "stream_total_timeouts": 0,
    "upstream_errors": 0, "client_disconnects": 0,
    "internal_retries": 0, "active_streams": 0, "queue_now": 0,
    "queue_wait_peak": 0.0,
    "ttft_buckets": {
        "lt1": 0, "1to5": 0, "5to30": 0, "30to60": 0,
        "60to120": 0, "120to300": 0, "gt300": 0},
    "queue_wait_buckets": {"lt1": 0, "1to10": 0, "gt10": 0},
}
_HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
        "te", "trailers", "transfer-encoding", "upgrade", "host",
        "content-length", "content-type"}
# authorization 透传（上游 vLLM 鉴权）


def ttft_bucket(v: float) -> None:
    d = METRICS["ttft_buckets"]
    if v < 1: d["lt1"] += 1
    elif v < 5: d["1to5"] += 1
    elif v < 30: d["5to30"] += 1
    elif v < 60: d["30to60"] += 1
    elif v < 120: d["60to120"] += 1
    elif v < 300: d["120to300"] += 1
    else: d["gt300"] += 1


def qbucket(v: float) -> None:
    d = METRICS["queue_wait_buckets"]
    if v < 1: d["lt1"] += 1
    elif v < 10: d["1to10"] += 1
    else: d["gt10"] += 1


# ---------------------------------------------------------------- 工具
async def acquire_or_none() -> float | None:
    t0 = time.monotonic()
    METRICS["queue_now"] += 1
    try:
        timeout = QUEUE_TIMEOUT if QUEUE_TIMEOUT > 0 else 0.001
        await asyncio.wait_for(SEM.acquire(), timeout=timeout)
        wait = time.monotonic() - t0
        qbucket(wait)
        METRICS["queue_wait_peak"] = max(METRICS["queue_wait_peak"], wait)
        return wait
    except asyncio.TimeoutError:
        METRICS["rejected_429_queue"] += 1     # 唯一计数点（dispatch 不再重复计）
        return None
    finally:
        METRICS["queue_now"] -= 1


def fwd_headers(request: web.Request) -> dict:
    out = {}
    for k, v in request.headers.items():
        if k.lower() in _HOP:
            continue                                    # authorization 透传
        out[k] = v
    out["Content-Type"] = request.headers.get("Content-Type", "application/json")
    xff = request.headers.get("X-Forwarded-For")
    out["X-Forwarded-For"] = (
        f"{xff}, {request.remote}" if xff else str(request.remote))
    # Host 不硬编码：aiohttp 按目标 URL 自动生成
    return out


def upstream_url(request: web.Request) -> str:
    return UPSTREAM + request.raw_path        # raw_path 含 query，未解码，防错位


def is_stream(body: bytes) -> bool:
    """仅显式布尔 stream:true 走流式（字符串/数字等真值一律非流式）。
    rc3.4 prefilter：body 无 "stream" 键字节串则跳过 json.loads（语义零变化
    ——无该键的 JSON 与非法 body 原本就返回 False；最常见非流式请求全免解析）。"""
    if b'"stream"' not in body:
        return False
    try:
        v = json.loads(body).get("stream")
        return v is True
    except Exception:
        return False


def maybe_inject(body: bytes, path: str) -> bytes:
    """rc3.6（S2 下沉，原 8003 _inject_enable_thinking）：POST chat 路径缺省注入
    chat_template_kwargs.enable_thinking=true。确定性变换（同 body 恒同输出），
    在 body_key 之前执行 → 去重键对注入后 body 计算且跨开关各自稳定。
    字节豁免优先：body 已含 "enable_thinking"（用户显式管理）→ 跳注入跳 parse
    （保 rc3.4 prefilter 收益）；非法 JSON / 非法顶层结构 → 原样返回走原逻辑。"""
    if not INJECT_ENABLE_THINKING:
        return body
    if ("/chat/completions" not in path) and ("/responses" not in path):
        return body
    if b'"enable_thinking"' in body:
        return body                          # 显式管理：不覆盖（T22 断言 2）
    try:
        obj = json.loads(body)
        if not isinstance(obj, dict):
            return body
        kwargs = obj.get("chat_template_kwargs")
        if not isinstance(kwargs, dict):
            kwargs = {}
        kwargs.setdefault("enable_thinking", True)
        obj["chat_template_kwargs"] = kwargs
        return json.dumps(obj).encode()
    except Exception:
        return body                          # 非法 body：跳注入，走原转发逻辑


MAX_HASH_BYTES = 1 << 20                    # 只 hash 前 1MB（分块流式，防超大 body 全量驻留）


def body_key(body: bytes) -> str:
    """去重键：size + 前 1MB 分块 sha256（长 body 不整段驻留内存）。"""
    h = hashlib.sha256()
    h.update(str(len(body)).encode() + b":")
    h.update(body[:MAX_HASH_BYTES])
    return h.hexdigest()


def resp_429(msg: str, wait: int) -> web.Response:
    return web.json_response(
        {"error": {"message": msg, "type": "gateway_admission", "code": 429}},
        status=429, headers={"Retry-After": str(wait)})


def err_frame(etype: str, msg: str) -> bytes:
    """固定文案错误帧 + [DONE] 终止符（细节仅入日志，不入帧）。"""
    return (b"data: " + json.dumps({"error": {
        "message": msg, "type": etype}}).encode() + b"\n\n" + DONE_MARK)


# ---------------------------------------------------------------- 流式
async def handle_stream(request: web.Request, body: bytes,
                        session: ClientSession) -> web.StreamResponse:
    """四阶段：占位去重(原子) → 早开流+心跳 → producer(建连/首字节/TTFT预算/泵送)
    ∥ consumer(客户端写循环) 并行 → 排空收尾。rc3.3：consumer 与阶段2并行，
    心跳实时下发（不再积压到首字节后）；约束：早开流后不向外抛异常（一切失败
    以错误帧+[DONE] 收尾）；信号量由 dispatch 持有；慢读客户端由
    WRITE_TIMEOUT/TOTAL_STREAM_TIMEOUT 兜底。"""
    key = body_key(body)

    # 原子占位（事件循环单线程：check+set 无间隙，TOCTOU 根除）
    if DEDUP_ENABLE:
        if key in INFLIGHT:
            METRICS["rejected_429_duplicate"] += 1
            return resp_429(
                "identical request already in flight (gateway dedup); "
                "retrying restarts full prefill — wait for the in-flight one",
                max(60, int(HEARTBEAT_INTERVAL * 8)))
        INFLIGHT[key] = time.monotonic()
        registered = True
    else:
        registered = False

    resp = web.StreamResponse(status=200, headers={
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        "X-Gateway": VERSION,
    })
    try:
        await resp.prepare(request)
    except BaseException:                  # prepare 失败（客户端早断）：占位必须回收
        if registered:                    # （rc3.3 补：此处位于下方 try/finally 之外，
            INFLIGHT.pop(key, None)       #   原样穿透会导致去重键泄漏→同 body 永久 429）
        raise

    METRICS["streams_total"] += 1
    METRICS["active_streams"] += 1
    t0 = time.monotonic()

    upstream = None
    q: asyncio.Queue = asyncio.Queue(maxsize=256)
    DONE = object()
    first_seen = asyncio.Event()             # 首字节到达（TTFT 预算监管点）
    tasks: list[asyncio.Task] = []

    async def heartbeat() -> None:
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            try:
                q.put_nowait(HEARTBEAT)     # 队列满即丢弃：有数据在途等效保活
            except asyncio.QueueFull:
                pass

    async def producer() -> None:
        """rc3.3：建连 + 首字节（共享 TTFT 预算）+ 持续泵送，收敛为单一 producer。
        心跳实时化前提：消费循环（consumer）已并行运行，本任务只管生产。
        any-exit 保证：first_seen 必置位（主流程不被挂死）、DONE 必入队
        （consumer 收尾依据）——全部走 finally，无裸退出路径。"""
        nonlocal upstream
        try:
            # ---- 建连（重试循环；引擎拒绝/连接失败 → 错误帧 + return，DONE 由 finally）
            last_err = ""
            for attempt in range(1 + RETRY_CONNECT):
                try:
                    u = await session.post(
                        upstream_url(request), data=body,
                        headers=fwd_headers(request),
                        timeout=ClientTimeout(total=None, sock_connect=10))
                    if u.status >= 500 and attempt < RETRY_CONNECT:
                        u.release()
                        METRICS["internal_retries"] += 1
                        await asyncio.sleep(0.5 * (attempt + 1))
                        continue
                    if u.status != 200:                 # 引擎明确拒绝
                        METRICS["upstream_errors"] += 1
                        log.warning("upstream rejected %s %s body=%.300s",
                                    u.status, request.raw_path, await u.text())
                        u.close()                       # 不留句柄，防误读 error body
                        q.put_nowait(err_frame(
                            "gateway_upstream",
                            "upstream rejected the request (see gateway log)"))
                        return
                    upstream = u
                    break
                except Exception as e:
                    last_err = repr(e)
                    if attempt < RETRY_CONNECT:
                        METRICS["internal_retries"] += 1
                        await asyncio.sleep(0.5 * (attempt + 1))
                        continue
                    METRICS["upstream_errors"] += 1
                    log.warning("upstream connect failed %s: %s",
                                request.raw_path, last_err)
                    q.put_nowait(err_frame(
                        "gateway_upstream",
                        "upstream connect failed (see gateway log)"))
                    return

            # ---- 首字节：与建连共享同一 TTFT 预算（以入口 t0 为基准，connect 已
            #      耗时扣除；max(0.1,·) 保证耗尽时极短超时即触发超时分支，无负数/
            #      零 timeout。FIRST_TOKEN_TIMEOUT<=0 = 关闭预算，不限时）
            try:
                if FIRST_TOKEN_TIMEOUT > 0:
                    remaining = max(
                        0.1, FIRST_TOKEN_TIMEOUT - (time.monotonic() - t0))
                    first = await asyncio.wait_for(
                        upstream.content.readany(), timeout=remaining)
                else:
                    first = await upstream.content.readany()
            except asyncio.TimeoutError:
                METRICS["first_token_timeouts"] += 1
                log.warning("first-token timeout %.0fs %s",
                            FIRST_TOKEN_TIMEOUT, request.raw_path)
                q.put_nowait(err_frame(
                    "gateway_first_token_timeout",
                    f"no first token from engine within "
                    f"{FIRST_TOKEN_TIMEOUT:.0f}s (long prefill); "
                    f"do NOT blind-retry with same payload"))
                return
            except asyncio.CancelledError:
                raise
            except Exception as e:
                METRICS["upstream_errors"] += 1
                log.warning("first read failed %s: %r", request.raw_path, e)
                q.put_nowait(err_frame(
                    "gateway_upstream",
                    "upstream stream failed before first token (see gateway log)"))
                return

            ttft = time.monotonic() - t0
            ttft_bucket(ttft)
            log.info("stream first-token ttft=%.2fs path=%s", ttft, request.path)
            first_seen.set()                  # 首字节到：TTFT 预算监管结束

            # ---- 持续泵送（rc3.4 背压化：await put 阻塞等 consumer 消费，等价引擎
            #      TCP 背压，数据帧零丢弃——慢而未死客户端不再静默截断；
            #      put 无超时（等价 v1 直通语义），readany 仍受 CHUNK_IDLE 约束，
            #      两者分 try 捕获，超时语义互不污染）
            data = first
            try:
                while data:
                    await q.put(data)
                    try:
                        data = await asyncio.wait_for(
                            upstream.content.readany(),
                            timeout=CHUNK_IDLE_TIMEOUT)
                    except asyncio.TimeoutError:
                        METRICS["chunk_idle_timeouts"] += 1
                        q.put_nowait(err_frame(
                            "gateway_chunk_idle",
                            f"upstream stream idle > {CHUNK_IDLE_TIMEOUT:.0f}s "
                            f"after first token"))
                        return
            except asyncio.CancelledError:
                raise
            except Exception as e:
                METRICS["upstream_errors"] += 1
                log.warning("pump error %s: %r", request.path, e)
        except asyncio.CancelledError:
            raise
        finally:
            first_seen.set()
            await q.put(DONE)                 # 阻塞式保证 DONE 必达（consumer 收尾）

    async def consumer() -> None:
        """rc3.3 心跳实时化核心：resp.prepare 后立即启动的客户端写循环，与
        producer 完全并行——阶段2（建连 + 长 prefill 等待）期间心跳即实时下发，
        不再积压到首字节后同批涌出。"""
        try:
            while True:
                item = await q.get()
                if item is DONE:
                    break
                if time.monotonic() - t0 > TOTAL_STREAM_TIMEOUT:
                    METRICS["stream_total_timeouts"] += 1
                    log.warning("stream total > %.0fs, cut: %s",
                                TOTAL_STREAM_TIMEOUT, request.path)
                    break
                await asyncio.wait_for(resp.write(item), timeout=WRITE_TIMEOUT)
        except asyncio.TimeoutError:                     # 写客户端超时（慢读）
            METRICS["write_timeouts"] += 1
            log.warning("client write timeout %.0fs: %s",
                        WRITE_TIMEOUT, request.path)
        except (ConnectionResetError, asyncio.CancelledError):
            METRICS["client_disconnects"] += 1

    hb = asyncio.create_task(heartbeat())
    consumer_t = asyncio.create_task(consumer())
    tasks.extend((hb, consumer_t))

    def finish_err(etype: str, msg: str) -> None:
        q.put_nowait(err_frame(etype, msg))
        q.put_nowait(DONE)

    producer_t = asyncio.create_task(producer())
    tasks.append(producer_t)
    try:
        # ---- 阶段2 预算监管：首字节（first_seen）须在 TTFT 预算内到达。
        #      超时则取消 producer（其 finally 保证 DONE 入队），consumer 收到
        #      错误帧后自然收尾；预算只管到首字节，不约束后续整流时长
        #      （整流由 TOTAL_STREAM_TIMEOUT 管，避免长生成流被 TTFT 误杀）。
        try:
            if FIRST_TOKEN_TIMEOUT > 0:
                await asyncio.wait_for(
                    first_seen.wait(), timeout=FIRST_TOKEN_TIMEOUT)
            else:
                await first_seen.wait()
        except asyncio.TimeoutError:
            producer_t.cancel()
            METRICS["first_token_timeouts"] += 1
            log.warning("first-token timeout %.0fs %s",
                        FIRST_TOKEN_TIMEOUT, request.raw_path)
            finish_err("gateway_first_token_timeout",
                       f"no first token from engine within "
                       f"{FIRST_TOKEN_TIMEOUT:.0f}s (long prefill); "
                       f"do NOT blind-retry with same payload")

        # ---- 阶段3：等 consumer 排空退出（producer 的数据/错误帧/DONE 已入队）
        await consumer_t
        return resp
    except (ConnectionResetError, asyncio.CancelledError):
        METRICS["client_disconnects"] += 1
        raise
    except Exception as e:                              # 兜底：绝不向外裸抛挂死客户端
        log.exception("stream handler error: %r", e)
        try:
            finish_err("gateway_internal", "gateway internal error (see log)")
            await asyncio.wait_for(resp.write_eof(), timeout=WRITE_TIMEOUT)
        except (Exception, asyncio.CancelledError):     # rc3.5.1：含取消（见 finally 注）
            resp.force_close()
        return resp
    finally:
        # rc3.5.1：同步清理先行——CancelledError 传播路径下，finally 内任何 await
        # （含 wait_for(write_eof)）都会立即再抛 CancelledError（BaseException，
        # except Exception 捕不住），原先排在其后的 INFLIGHT.pop/active-=1 会被
        # 全部跳过（active 永久漂移 +1；DEDUP=on 时键泄漏 → 同 payload 永久 429）。
        # 顺序反转后：先完成全部同步清理，write_eof 挪到最后且自吞取消。
        for t in tasks:
            t.cancel()
        if upstream is not None:
            upstream.close()
        if registered:
            INFLIGHT.pop(key, None)
        METRICS["active_streams"] -= 1
        try:
            # rc3.5：write_eof 的内部 drain 不受 WRITE_TIMEOUT 约束（那只管
            # resp.write）——慢读客户端在切流后仍不读 → eof drain 永久阻塞 →
            # finally 卡死 → dispatch 的 SEM.release 永不执行（槽泄漏：6 个慢
            # 客户端耗尽全站并发，直至重启）。超时即放弃，连接由服务端关闭兜底。
            await asyncio.wait_for(resp.write_eof(), timeout=WRITE_TIMEOUT)
        except (Exception, asyncio.CancelledError):
            # 超时/异常/取消路径都 force_close：aiohttp 在 handler 返回后的内部
            # finish 路径会再次尝试 write_eof 并 drain（同一阻塞面）——force_close
            # 使其改为直接 close 连接（非阻塞）。已取消协程内吞 CancelledError
            # 是合法收尾（web_protocol 已在关闭连接，重抛无意义）
            resp.force_close()


# ---------------------------------------------------------------- 非流式
async def relay_plain(request: web.Request, body: bytes,
                      session: ClientSession) -> web.Response:
    try:
        async with session.request(              # 原方法转发（PUT/DELETE/OPTIONS 不破坏）
                request.method, upstream_url(request), data=body,
                headers=fwd_headers(request),
                timeout=ClientTimeout(total=NONSTREAM_TOTAL_TIMEOUT)) as up:
            return web.Response(status=up.status,
                                content_type=up.content_type or "application/json",
                                body=await up.read())
    except asyncio.TimeoutError:
        METRICS["upstream_errors"] += 1
        return web.json_response(
            {"error": {"message": f"gateway: upstream non-stream timeout "
                                  f">{NONSTREAM_TOTAL_TIMEOUT:.0f}s",
                       "type": "gateway_timeout"}}, status=504)
    except Exception as e:
        METRICS["upstream_errors"] += 1
        log.warning("relay_plain failed %s %s: %r",
                    request.method, request.raw_path, e)
        return web.json_response(
            {"error": {"message": "upstream connect failed",
                       "type": "gateway_upstream"}}, status=502)


async def relay_get(request: web.Request, session: ClientSession) -> web.Response:
    try:
        async with session.get(upstream_url(request), headers=fwd_headers(request),
                               timeout=ClientTimeout(total=30)) as up:
            return web.Response(status=up.status, content_type=up.content_type,
                                body=await up.read())
    except Exception:
        return web.json_response(
            {"error": {"message": "upstream failed",
                       "type": "gateway_upstream"}}, status=502)


# ---------------------------------------------------------------- 入口
def gw_authorized(request: web.Request) -> bool:
    if not GW_API_KEY:
        return True
    # 常量时间比较（rc3.4）：防时序侧信道逐字节探测 key
    return hmac.compare_digest(request.headers.get("Authorization", ""),
                               f"Bearer {GW_API_KEY}")


async def dispatch(request: web.Request):
    METRICS["requests_total"] += 1
    if request.path.startswith("/gw/"):
        if not gw_authorized(request):
            return web.json_response(
                {"error": {"message": "unauthorized", "type": "gw_auth"}},
                status=401)
        if request.path == "/gw/health":
            return web.json_response({"status": "ok", "version": VERSION})
        if request.path == "/gw/metrics":
            METRICS["uptime_sec"] = int(time.time() - STARTED_AT)
            return web.json_response(METRICS)
        return web.json_response({"error": "not found"}, status=404)

    # GET/HEAD 免并发槽（轻量读，不占推理槽；30s 自身超时）
    if request.method in ("GET", "HEAD"):
        try:
            return await relay_get(request, request.app["client"])
        except Exception:
            return web.json_response(
                {"error": {"message": "upstream failed",
                           "type": "gateway_upstream"}}, status=502)

    wait = await acquire_or_none()
    if wait is None:
        return resp_429(
            f"gateway at capacity (MAX_CONCURRENCY={MAX_CONCURRENCY}); "
            f"engine busy — retry after cool-down", 30)
    try:
        session: ClientSession = request.app["client"]
        body = await request.read()
        if request.method == "POST":
            body = maybe_inject(body, request.path)   # rc3.6：注入先于流式判定与去重键
        if request.method == "POST" and is_stream(body):
            return await handle_stream(request, body, session)
        return await relay_plain(request, body, session)
    except (ConnectionResetError, asyncio.CancelledError):
        METRICS["client_disconnects"] += 1
        raise
    except Exception as e:
        log.exception("dispatch failed: %r", e)
        return web.json_response(
            {"error": {"message": "gateway internal error",
                       "type": "gateway_internal"}}, status=500)
    finally:
        SEM.release()


async def make_app() -> web.Application:
    # 64MB：600K token JSON 实测数 MB 级；防超大 body×并发 的内存峰值
    app = web.Application(client_max_size=64 * 1024 * 1024)
    app["client"] = ClientSession(
        timeout=ClientTimeout(total=None),
        cookie_jar=DummyCookieJar())               # 不跨客户端回带 Cookie
    app.router.add_route("*", "/{tail:.*}", dispatch)
    app.on_cleanup.append(_close_session)
    return app


async def _close_session(app: web.Application) -> None:
    await app["client"].close()


def main() -> None:
    log.info("%s %s->%s conc=%d ttft=%.0fs idle=%.0fs hb=%.0fs q=%.0fs "
             "write_to=%.0fs total_to=%.0fs dedup=%s auth=%s",
             VERSION, f"0.0.0.0:{PORT}", UPSTREAM, MAX_CONCURRENCY,
             FIRST_TOKEN_TIMEOUT, CHUNK_IDLE_TIMEOUT, HEARTBEAT_INTERVAL,
             QUEUE_TIMEOUT, WRITE_TIMEOUT, TOTAL_STREAM_TIMEOUT,
             DEDUP_ENABLE, "on" if GW_API_KEY else "off")
    web.run_app(make_app(), host="0.0.0.0", port=PORT, print=None,
                shutdown_timeout=60)


if __name__ == "__main__":
    main()
