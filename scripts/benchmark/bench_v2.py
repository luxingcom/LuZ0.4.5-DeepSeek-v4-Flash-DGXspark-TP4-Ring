#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 关联文档: file:///opt/_PH_INSTALL_/deliverables/engineering-assurance/nccl-benchmark-v2-report-qa-2026-08-16.md（v2 基准判读报告）
#          file:///opt/_PH_INSTALL_/deliverables/engineering-assurance/nccl-final-performance-baseline-2026-08-17.md（最终性能基线 v1.0）
# 凭据: 默认取环境变量 VLLM_API_KEY（显式 --key 优先），避免 key 落命令行/ps/日志（QA 整改 2026-08-17，C 类）
"""
bench_v2.py — vLLM v2 基准体系（DE 文本吞吐 / PR 纯 prefill 吞吐 / 接受率 / dspark 接受率 / monitor 隔离）
============================================================================================================

SRE 工程师 Rex 开发。独立于既有 bench_prefill_decode_async.py，避免破坏旧工具。

支持的测试矩阵（用户要求 + QA 方案 §6 R1-R9）：
  1. 并发档位      : --concurrency 1,2,4,6（每波 conc 在飞 = 真并发）
  2. DE 文本吞吐    : 输入 512 / 输出 4096 固定；任务类型 coding / json / prose 三套 prompt 模板；
                     ignore_eos=true 强制满长 4096（R3）；每种类型独立测量 decode 吞吐
  3. PR 吞吐        : 随机前缀 512/2048/8192/32768/131076，max_tokens=1 纯 prefill；
                     前缀纯随机（无任务模板，R8 首选），固定 seed 可比、同 run 请求内容不同防 prefix-cache
  4. 接受率         : 每档 ok/http_err/timeout/conn_err/model_err/other 分类（R4 聚合口径亦输出）
  5. dspark 接受率  : 每档窗口前/后采样 /metrics 的 spec_decode counters（R5）：
                     vllm:spec_decode_num_drafts_total / *_draft_tokens_total / *_accepted_tokens_total /
                     *_accepted_tokens_per_pos_total{position=0..4}
                     输出 dspark_accept_rate / dspark_per_pos_accept[] / dspark_draft_per_request
  6. 隔离与时间对齐  : 每档独立 monitor（vllm:num_requests_running，baseline/during/post 三段，
                     running==C 判据）；档间冷却可配置；start/end ISO 时间戳
  7. 批次 manifest  : manifest_<group>.json（R7）：32 档 start/end、总耗时、环境快照、
                     dspark 计数器起止值、engine/rounds/temperature/seed
  8. 落盘结构       : 默认 verification-logs/BENCHV2_<ts>/<group>/（rows+summary+monitor+bench+manifest+precheck，R9）
  执行顺序         : 方案 §7.1 = 按并发档分组（C1: DE3+PR5 → C2 → C4 → C6），每档 monitor 独立纯净窗口

依赖：requests（系统 python3 已装）；monitor/dspark 读 vLLM /metrics。
并发实现：requests + ThreadPoolExecutor（= 方案统一 engine=threads，与 v1 一致）。
dspark 指标经实测在当前生产 /metrics 可读（累计 counter，测试时随请求增长）。

用法示例：
  # 全矩阵（DE + PR，默认目录）
  python3 bench_v2.py --endpoint http://_PH_NODE_IP_:8001/v1 --key <KEY> \
      --concurrency 1,2,4,6 --run-type both --rounds 3 --cooldown 30 --precheck

  # 指定输出目录
  python3 bench_v2.py --endpoint http://_PH_NODE_IP_:8001/v1 --key <KEY> \
      --run-type both --concurrency 1,2,4,6 --rounds 3 --out /opt/_PH_INSTALL_/results_v2_full

  # dry-run（不占 GPU）
  python3 bench_v2.py --endpoint http://_PH_NODE_IP_:8001/v1 --key <KEY> --dry-run
"""

import argparse
import csv
import json
import os
import random
import re
import signal
import statistics
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import requests

# ---------------------------------------------------------------------------
# 常量与默认矩阵
# ---------------------------------------------------------------------------
DEFAULT_CONCURRENCY = [1, 2, 4, 6]
DEFAULT_PREFIX_LENS = [512, 2048, 8192, 32768, 131076]
DEFAULT_TASKS = ["coding", "json", "prose"]
DEFAULT_ROUNDS = 3
DE_INPUT_LEN = 512          # DE 输入固定
DE_OUTPUT_LEN = 4096        # DE 输出固定（max_tokens）
PR_OUTPUT_TOKENS = 1        # PR 输出 1 token
TEMPERATURE = 0.6           # 方案统一 temperature
ENGINE = "threads"          # requests + ThreadPoolExecutor（与 v1 threads 一致）
CALIB_UNITS = 100
MAX_TOKENS_PROBE = 1
DEFAULT_REQUEST_TIMEOUT = 1800.0   # 单请求总超时（秒）
DEFAULT_CONNECT_TIMEOUT = 60.0
DEFAULT_COOLDOWN = 30.0            # 档间冷却（秒）
DEFAULT_MONITOR_INTERVAL = 1.0     # monitor 采样间隔（秒）；快速档需更密采样
BASELINE_SAMPLES = 5               # 每档 start 前/end 后的 baseline/post 采样数
CALIB_SAMPLE_RATIO = 0.88          # 填充单位折算系数（同旧脚本，防超长）
DEFAULT_BASE_DIR = "verification-logs"
DEFAULT_PRECHECK_HOSTS = ["node01", "node02", "node03", "node04"]

# ---------------------------------------------------------------------------
# 任务模板（DE 三类；配合 ignore_eos 打满 4096）
# ---------------------------------------------------------------------------
TASK_TEMPLATES = {
    "coding": (
        "请用 Python 实现一个大型工具库 process_lib，包含以下模块并给出完整可运行代码、docstring 与 pytest 测试：\n"
        "1) process_records(records: list[dict]) -> dict：按 category 分组统计 avg_score/count，按 count 降序返回；\n"
        "2) DataPipeline 类：支持 read/transform/aggregate/write 四阶段，含重试与日志；\n"
        "3) cli 入口：argparse 解析 --input/--output/--verbose/--workers。\n"
        "代码要尽量长而完整，覆盖类型注解、边界处理、异常处理与注释。只输出代码，不要解释。"
    ),
    "json": (
        "请生成一个大型 JSON 对象（只输出 JSON，不要任何其他文本）：描述一个包含 200 名员工的组织。\n"
        "每个员工含 id / name / role / department / skills(数组，5-10 项) / projects(数组，每项含 name/status/deadline/milestones数组) / "
        "metrics(含 efficiency/quality/velocity 三个 0-100 数值) / tags(数组) / active(bool)。\n"
        "status 必须取 planned|in_progress|done 之一；deadline 为 ISO 日期字符串；id 用 E001-E200。\n"
        "字段尽可能多、内容尽可能丰富，直接输出完整 JSON。"
    ),
    "prose": (
        "请以散文风格续写下面这段文字，写成一篇长散文，内容要非常长、细节丰富、有画面感：\n"
        "夜色渐深，小镇的灯火次第亮起。巷口的梧桐树下，风把最后一片落叶送进了邮筒……\n"
        "请持续展开叙述：人物的身世、巷弄的景致、往事与此刻的交织、四季的流转，逐步推进到结尾，"
        "写到 8000 字以上。语言优美、自然，不要总结、不要解释、不要评论写作本身。"
    ),
}
STATUS_LABELS = ["ok", "http_err", "timeout", "conn_err", "model_err", "other"]

# ---------------------------------------------------------------------------
# 随机前缀流（固定 seed：跨 run 可比；请求间顺序消费 → 同 run 内内容不同避 prefix-cache）
# ---------------------------------------------------------------------------
def _rand_unit(rng):
    return f"seg_{rng.getrandbits(128):032x}_{rng.getrandbits(128):032x}_{rng.randrange(0, 10**9):09d}"


class SeededPromptStream:
    """每个档位一个流。seed = 基础 seed + 档位序号，保证同档跨 run 内容完全一致。"""

    def __init__(self, seed, tpu, task=None):
        self.rng = random.Random(seed)
        self.tpu = tpu
        self.task = task

    def next_prompt(self, target_tokens):
        units = max(1, int(target_tokens * CALIB_SAMPLE_RATIO / self.tpu))
        parts = [_rand_unit(self.rng) for _ in range(units)]
        filler = "\n".join(parts)
        if self.task is None:
            return filler + "\n"   # PR：纯随机前缀（无任务模板）
        return f"{filler}\n\n[任务]\n{TASK_TEMPLATES[self.task]}"


# ---------------------------------------------------------------------------
# 单请求（requests + SSE 流式；返回统一 result dict）
# ---------------------------------------------------------------------------
def run_one(session, url, headers, model, prompt, max_tokens, timeout, connect_timeout, ignore_eos):
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": TEMPERATURE,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if ignore_eos:
        payload["ignore_eos"] = True   # R3：DE 强制满长
    t0 = time.time()
    deadline = t0 + timeout   # 硬性 wall-clock 截止（requests 的 read timeout 是"每读"而非总量，须自行兜底）
    try:
        # FIX-20260816: 放开读超时到 request wall-clock timeout（原 min(timeout,60) 硬编码 60s
        # 会导致长前缀并发下首块等待 >60s 而误判超时；wall-clock 截止由 deadline 兜底）
        r = session.post(url, json=payload, headers=headers, stream=True,
                         timeout=(connect_timeout, timeout))
    except (requests.exceptions.Timeout, requests.exceptions.ReadTimeout) as e:
        return _err("timeout", f"timeout:{type(e).__name__} after {timeout}s")
    except requests.exceptions.ConnectionError as e:
        return _err("conn_err", f"conn:{type(e).__name__}:{e}")
    except Exception as e:  # noqa: BLE001
        return _err("other", f"request:{type(e).__name__}:{e}")

    if r.status_code != 200:
        try:
            body = r.text[:200]
        except Exception:  # noqa: BLE001
            body = ""
        return _err("http_err", f"http {r.status_code}: {body}")

    first_ts = time.time()
    ttft = None
    last = None
    usage = None
    finish_reason = None
    buf = ""
    try:
        for raw in r.iter_lines(decode_unicode=True):
            if time.time() > deadline:
                return _err("timeout", f"wall-clock deadline {timeout}s exceeded (total)")
            if not raw:
                continue
            buf += raw + "\n"
            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                line = line.strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    obj = json.loads(data)
                except json.JSONDecodeError:
                    continue
                now = time.time()
                choices = obj.get("choices")
                if choices:
                    delta = choices[0].get("delta") or {}
                    if delta.get("content") and ttft is None:
                        ttft = now - first_ts
                    fr = choices[0].get("finish_reason")
                    if fr:
                        finish_reason = fr
                        last = now - first_ts
                if obj.get("usage"):
                    usage = obj["usage"]
        if ttft is None:
            ttft = time.time() - first_ts
        if last is None:
            last = time.time() - first_ts
    except (requests.exceptions.Timeout, requests.exceptions.ReadTimeout) as e:
        # FIX-20260816: requests.ReadTimeout 非 Timeout 子类（继承内置 TimeoutError），
        # 此前落到 Exception 被归为 other；现显式归 timeout 类
        return _err("timeout", f"stream-timeout:{type(e).__name__}")
    except Exception as e:  # noqa: BLE001
        return _err("other", f"stream:{type(e).__name__}:{e}")

    if finish_reason == "error":
        return _err("model_err", f"finish_reason=error (usage={usage})")
    return _build(usage, ttft, last)


def _err(status, msg):
    return {"ok": False, "status": status, "err": msg,
            "prompt_tokens": None, "completion_tokens": None,
            "ttft_s": None, "total_s": None, "prefill_tps": None, "decode_tps": None}


def _build(usage, ttft, total):
    pt = (usage or {}).get("prompt_tokens", 0) or 0
    ct = (usage or {}).get("completion_tokens", 0) or 0
    if pt <= 0 or ct <= 0:
        return _err("model_err", f"no-usage pt={pt} ct={ct}")
    return {
        "ok": True, "status": "ok", "err": "",
        "prompt_tokens": pt, "completion_tokens": ct,
        "ttft_s": round(ttft, 4), "total_s": round(total, 4),
        "prefill_tps": round(pt / ttft, 2) if ttft > 0 else None,
        "decode_tps": round((ct - 1) / (total - ttft), 2) if (total - ttft) > 1e-6 else None,
    }


# ---------------------------------------------------------------------------
# 校准（非流式短请求读 usage.prompt_tokens → tokens/unit）
# ---------------------------------------------------------------------------
def calibrate(session, url, headers, model, timeout, connect_timeout):
    rng = random.Random(20260816)
    prompt = "\n".join(_rand_unit(rng) for _ in range(CALIB_UNITS))
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": MAX_TOKENS_PROBE,
        "temperature": TEMPERATURE,
        "stream": False,
    }
    try:
        r = session.post(url, json=payload, headers=headers, timeout=(connect_timeout, timeout))
        r.raise_for_status()
        data = r.json()
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"calib request failed: {e}") from e
    pt = (data.get("usage") or {}).get("prompt_tokens")
    if not pt:
        raise RuntimeError(f"calib no usage: {data.get('id')}")
    tpu = pt / CALIB_UNITS
    print(f"[calib] prompt_tokens={pt}, tokens/unit≈{tpu:.2f}", flush=True)
    return tpu


# ---------------------------------------------------------------------------
# 波 = conc 并发在飞；档 = rounds 波
# ---------------------------------------------------------------------------
def run_wave(stream, session, url, headers, model, target_tokens, max_tokens, conc,
             timeout, connect_timeout, ignore_eos):
    prompts = [stream.next_prompt(target_tokens) for _ in range(conc)]
    with ThreadPoolExecutor(max_workers=conc) as ex:
        futures = [ex.submit(run_one, session, url, headers, model, p, max_tokens,
                             timeout, connect_timeout, ignore_eos) for p in prompts]
        return [f.result() for f in futures]


# ---------------------------------------------------------------------------
# /metrics 解析：running + dspark spec_decode counters（R5）
# ---------------------------------------------------------------------------
def _metric_val(line):
    try:
        return float(line.split()[-1])
    except (ValueError, IndexError):
        return None


def parse_metrics(text):
    """返回 dict：running / drafts_total / draft_tokens_total / accepted_tokens_total / accepted_per_pos{}。"""
    snap = {"running": None, "drafts_total": None, "draft_tokens_total": None,
            "accepted_tokens_total": None, "accepted_per_pos": {}}
    for line in text.splitlines():
        if line.startswith("vllm:num_requests_running"):
            snap["running"] = _metric_val(line)
        elif line.startswith("vllm:spec_decode_num_drafts_total"):
            snap["drafts_total"] = _metric_val(line)
        elif line.startswith("vllm:spec_decode_num_draft_tokens_total"):
            snap["draft_tokens_total"] = _metric_val(line)
        elif line.startswith("vllm:spec_decode_num_accepted_tokens_total"):
            snap["accepted_tokens_total"] = _metric_val(line)
        elif line.startswith("vllm:spec_decode_num_accepted_tokens_per_pos_total"):
            m = re.search(r'position="(\d+)"', line)
            if m:
                snap["accepted_per_pos"][int(m.group(1))] = _metric_val(line)
    return snap


def read_metrics(metrics_url, headers):
    try:
        rr = requests.get(metrics_url, headers=headers, timeout=(10, 20))
        if rr.status_code != 200:
            return None
        return parse_metrics(rr.text)
    except Exception:  # noqa: BLE001
        return None


def _diff(end, start):
    if end is None or start is None:
        return None
    return max(0.0, end - start)


def dspark_stats(snap_start, snap_end, requests_total):
    """由档前/档后两个 /metrics 快照计算 dspark 投机解码接受率（R5）。"""
    if snap_start is None or snap_end is None:
        return {"available": False, "note": "metrics snapshot unavailable"}
    d_drafts = _diff(snap_end.get("drafts_total"), snap_start.get("drafts_total"))
    d_draft_tok = _diff(snap_end.get("draft_tokens_total"), snap_start.get("draft_tokens_total"))
    d_acc = _diff(snap_end.get("accepted_tokens_total"), snap_start.get("accepted_tokens_total"))
    per_pos = {}
    keys = set(snap_start.get("accepted_per_pos", {})) | set(snap_end.get("accepted_per_pos", {}))
    for pos in sorted(keys):
        per_pos[pos] = _diff(snap_end.get("accepted_per_pos", {}).get(pos),
                             snap_start.get("accepted_per_pos", {}).get(pos))
    return {
        "available": True,
        "delta_drafts": d_drafts,
        "delta_draft_tokens": d_draft_tok,
        "delta_accepted_tokens": d_acc,
        "delta_accepted_per_pos": per_pos,
        "dspark_accept_rate": (round(d_acc / d_draft_tok, 4) if d_draft_tok else None),
        "dspark_per_pos_accept": {p: (round(d / d_drafts, 4) if d_drafts else None) for p, d in per_pos.items()},
        "dspark_draft_per_request": (round(d_drafts / requests_total, 3) if requests_total and d_drafts is not None else None),
        "dspark_draft_tokens_per_request": (round(d_draft_tok / requests_total, 3) if requests_total and d_draft_tok is not None else None),
        "start": {k: snap_start.get(k) for k in ("drafts_total", "draft_tokens_total", "accepted_tokens_total")},
        "end": {k: snap_end.get(k) for k in ("drafts_total", "draft_tokens_total", "accepted_tokens_total")},
    }


# ---------------------------------------------------------------------------
# Monitor：每档独立，读 /metrics 的 vllm:num_requests_running，running==C 判据纯净
# ---------------------------------------------------------------------------
class Monitor(threading.Thread):
    def __init__(self, metrics_url, headers, interval, expected_c, tag):
        super().__init__(daemon=True)
        self.metrics_url = metrics_url
        self.headers = headers
        self.interval = interval
        self.expected_c = expected_c
        self.tag = tag
        self.samples = []          # list of (ts_epoch, running or None)
        self._stop_evt = threading.Event()
        self._errors = 0

    def run(self):
        while not self._stop_evt.is_set():
            ts = time.time()
            snap = read_metrics(self.metrics_url, self.headers)
            if snap is None:
                val = None
                self._errors += 1
            else:
                val = snap.get("running")
            self.samples.append((ts, val))
            self._stop_evt.wait(self.interval)

    def stop(self):
        self._stop_evt.set()
        self.join(timeout=10)

    def classify(self, t_start, t_end):
        base = [v for t, v in self.samples if t < t_start]
        dur = [v for t, v in self.samples if t_start <= t <= t_end]
        post = [v for t, v in self.samples if t > t_end]
        C = self.expected_c

        def stats(seq):
            vals = [v for v in seq if v is not None]
            if not vals:
                return {"samples": len(seq), "n_ok_read": 0, "min": None, "max": None, "mean": None}
            return {
                "samples": len(seq),
                "n_ok_read": len(vals),
                "min": min(vals),
                "max": max(vals),
                "mean": round(sum(vals) / len(vals), 3),
            }

        dur_vals = [v for v in dur if v is not None]
        reached_c = (dur_vals and max(dur_vals) >= C)
        overshoot = (dur_vals and max(dur_vals) > C)
        pure = bool(reached_c and not overshoot)
        n_during = len(dur)
        # 采样充分性：during 样本太少时无法观察到 running==C 峰值，判为 inconclusive 而非污染
        confidence = "high" if n_during >= 3 else "low"
        return {
            "expected_c": C,
            "baseline": stats(base),
            "during": stats(dur),
            "post": stats(post),
            "reached_full_concurrency": reached_c,
            "overshot": overshoot,
            "pure_running_eq_c": pure,
            "purity_confidence": confidence,
            "n_during_samples": n_during,
            "n_during_at_c": sum(1 for v in dur_vals if abs(v - C) < 0.5),
            "monitor_read_errors": self._errors,
        }


# ---------------------------------------------------------------------------
# 预检（可选，只读）：running==0 / dspark 起始值 / 四机 healthy·GPU 0%·无残留负载
# ---------------------------------------------------------------------------
def _ssh_one(host, cmd, timeout=25):
    try:
        out = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
                              host, cmd], capture_output=True, text=True, timeout=timeout)
        return {"reachable": True, "rc": out.returncode, "stdout": out.stdout[:2000], "stderr": out.stderr[:500]}
    except Exception as e:  # noqa: BLE001
        return {"reachable": False, "error": str(e)}


def run_precheck(metrics_url, headers, hosts):
    """只读预检。metrics 段权威；hosts 段 best-effort（SSH 失败仅记录不致命）。"""
    result = {"ts_iso": iso_now(), "metrics": {}, "hosts": {}}
    snap = read_metrics(metrics_url, headers)
    result["metrics"]["available"] = snap is not None
    if snap:
        result["metrics"]["running"] = snap.get("running")
        result["metrics"]["running_zero"] = (snap.get("running") == 0)
        result["metrics"]["dspark_counters_start"] = {
            "drafts_total": snap.get("drafts_total"),
            "draft_tokens_total": snap.get("draft_tokens_total"),
            "accepted_tokens_total": snap.get("accepted_tokens_total"),
            "accepted_per_pos": snap.get("accepted_per_pos"),
        }
    probe = ("docker ps --format '{{.Names}} {{.Status}}' | grep -E 'vllm-tp4-rank|sglang' || true; "
             "echo '---GPU---'; nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv,noheader,nounits 2>/dev/null || true; "
             "echo '---LOAD---'; pgrep -af 'bench_prefill|bench_v2|nccl_scan|nccl-test|sglang' || true")
    for h in hosts:
        result["hosts"][h] = _ssh_one(h, probe)
    return result


# ---------------------------------------------------------------------------
# 汇总
# ---------------------------------------------------------------------------
def summarize_tier(results, meta):
    total = len(results)
    oks = [r for r in results if r.get("ok")]
    by_status = {s: sum(1 for r in results if r.get("status") == s) for s in STATUS_LABELS}
    summ = dict(meta)
    summ["requests_total"] = total
    summ["requests_ok"] = len(oks)
    summ["acceptance_rate"] = round(len(oks) / total, 4) if total else None
    summ["acceptance"] = by_status
    # R4 聚合口径
    if total:
        summ["ok_rate"] = round(by_status["ok"] / total, 4)
        summ["network_reject_rate"] = round((by_status["http_err"] + by_status["timeout"] + by_status["conn_err"]) / total, 4)
        summ["model_error_rate"] = round(by_status["model_err"] / total, 4)
    summ["err_samples"] = [r.get("err") for r in results if not r.get("ok")][:3]

    for k in ("ttft_s", "total_s"):
        vals = [r[k] for r in oks if r.get(k) is not None]
        summ[f"p50_{k}"] = round(statistics.median(vals), 4) if vals else None
        if len(vals) >= 2:
            summ[f"min_{k}"] = round(min(vals), 4)
            summ[f"max_{k}"] = round(max(vals), 4)

    # DE：decode_tps 为主指标；PR：prefill_tps 为主指标
    pv = [r["prefill_tps"] for r in oks if r.get("prefill_tps") is not None]
    dv = [r["decode_tps"] for r in oks if r.get("decode_tps") is not None]
    summ["p50_prefill_tps"] = round(statistics.median(pv), 2) if pv else None
    summ["p50_decode_tps"] = round(statistics.median(dv), 2) if dv else None
    # completion_tokens 分布（R3 判读：DE 是否打满 max_tokens）
    cv = [r["completion_tokens"] for r in oks]
    if cv:
        summ["mean_completion_tokens"] = round(statistics.mean(cv), 1)
        summ["p50_completion_tokens"] = round(statistics.median(cv), 1)
        summ["min_completion_tokens"] = min(cv)
        summ["max_completion_tokens"] = max(cv)
        mt = meta.get("max_tokens") or 0
        summ["full_length_ratio"] = round(statistics.mean(cv) / mt, 4) if mt else None
    return summ


# ---------------------------------------------------------------------------
# 档位编排（§7.1：按并发档分组，C1: DE3+PR5 → C2 → C4 → C6）
# ---------------------------------------------------------------------------
def write_rows(writer, results, meta, wave_idx):
    for r in results:
        writer.writerow([
            meta["mode"], meta.get("task_type", ""), meta.get("prefix_len", ""),
            meta.get("input_len", ""), meta.get("output_len", ""), meta["concurrency"],
            wave_idx, r.get("ok"), r.get("status"),
            r.get("prompt_tokens", ""), r.get("completion_tokens", ""),
            r.get("ttft_s", ""), r.get("total_s", ""),
            r.get("prefill_tps", ""), r.get("decode_tps", ""), r.get("err", ""),
        ])


def build_plan(args, tpu):
    """返回档位列表（§7.1 顺序）。每档：mode/task_type/prefix_len/input_len/output_len/concurrency/max_tokens/seed"""
    concs = parse_list(args.concurrency)
    tasks = [t.strip() for t in args.task_type.split(",") if t.strip()]
    plens = parse_list(args.prefix_len)
    plan = []
    idx = 0
    for c in concs:
        if args.run_type in ("de", "both"):
            for task in tasks:
                plan.append({
                    "mode": "de", "task_type": task, "prefix_len": None,
                    "input_len": args.input_len, "output_len": args.output_len,
                    "concurrency": c, "max_tokens": args.output_len,
                    "ignore_eos": True, "seed": args.random_seed + idx,
                })
                idx += 1
        if args.run_type in ("pr", "both"):
            for plen in plens:
                plan.append({
                    "mode": "pr", "task_type": None, "prefix_len": plen,
                    "input_len": plen, "output_len": PR_OUTPUT_TOKENS,
                    "concurrency": c, "max_tokens": PR_OUTPUT_TOKENS,
                    "ignore_eos": False, "seed": args.random_seed + idx,
                })
                idx += 1
    return plan


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
_SIG_STATE = {"csv_f": None, "sum_path": None, "summaries": None, "group": None}


def _sig_flush_handler(signum, frame):
    try:
        if _SIG_STATE["csv_f"] is not None:
            _SIG_STATE["csv_f"].flush()
            print(f"[signal] {signal.Signals(signum).name}: CSV flushed", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"[signal] CSV flush 失败: {e}", flush=True)
    try:
        if _SIG_STATE["sum_path"] and _SIG_STATE["summaries"] is not None:
            with open(_SIG_STATE["sum_path"], "w", encoding="utf-8") as f:
                json.dump({"group": _SIG_STATE["group"], "partial": True,
                           "interrupted": True, "summary": _SIG_STATE["summaries"]},
                          f, ensure_ascii=False, indent=2)
            print(f"[signal] 部分 summary 已写: {_SIG_STATE['sum_path']}", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"[signal] summary 写盘失败: {e}", flush=True)
    os._exit(130 if signum == signal.SIGINT else 143)


def parse_list(s, cast=int):
    return [cast(x.strip()) for x in s.split(",") if x.strip()]


def iso_now():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def main():
    ap = argparse.ArgumentParser(description="vLLM v2 基准（DE 文本吞吐 / PR 纯 prefill / 接受率 / dspark / monitor）")
    ap.add_argument("--endpoint", required=True, help="vLLM /v1 地址，如 http://_PH_NODE_IP_:8001/v1")
    ap.add_argument("--key", default=os.environ.get("VLLM_API_KEY", ""),
                    help="API key（默认取 VLLM_API_KEY 环境变量；显式 --key 优先）")
    ap.add_argument("--model", default="deepseek-v4-flash-0731")
    ap.add_argument("--group", default="v2")
    ap.add_argument("--run-type", choices=["de", "pr", "both"], default="both")
    ap.add_argument("--concurrency", default="1,2,4,6")
    ap.add_argument("--task-type", default="coding,json,prose")
    ap.add_argument("--input-len", type=int, default=DE_INPUT_LEN, help="DE 输入 token 目标（默认 512）")
    ap.add_argument("--output-len", type=int, default=DE_OUTPUT_LEN, help="DE 输出 max_tokens（默认 4096）")
    ap.add_argument("--prefix-len", default="512,2048,8192,32768,131076", help="PR 前缀 token 目标")
    ap.add_argument("--rounds", type=int, default=DEFAULT_ROUNDS, help="每档波数（每波 conc 并发在飞）")
    ap.add_argument("--random-seed", type=int, default=20260816, help="随机前缀基础 seed（档位内偏移固定）")
    ap.add_argument("--uuid-prefix", action="store_true", help="每 run 混入时间熵重seed: 跨 run 内容不同, 杜绝 APC 跨 run 命中 (W9-R8 用户指令); 同 run 内仍确定性")
    ap.add_argument("--no-ignore-eos", action="store_true", help="关闭 DE 强制满长（默认 DE 开启 ignore_eos）")
    ap.add_argument("--base-dir", default=DEFAULT_BASE_DIR, help="默认输出根目录（未指定 --out 时用）")
    ap.add_argument("--out", default="", help="显式输出目录（覆盖默认 verification-logs/BENCHV2_<ts>/<group>）")
    ap.add_argument("--cooldown", type=float, default=DEFAULT_COOLDOWN, help="档间冷却秒数")
    ap.add_argument("--request-timeout", type=float, default=DEFAULT_REQUEST_TIMEOUT, help="单请求总超时（秒）")
    ap.add_argument("--connect-timeout", type=float, default=DEFAULT_CONNECT_TIMEOUT)
    ap.add_argument("--monitor-interval", type=float, default=DEFAULT_MONITOR_INTERVAL, help="monitor 采样间隔（秒）")
    ap.add_argument("--metrics-url", default="", help="vLLM /metrics 地址（默认由 endpoint 推导）")
    ap.add_argument("--no-monitor", action="store_true", help="关闭 monitor 与 dspark 采样")
    ap.add_argument("--precheck", action="store_true", help="跑批次前预检（running==0/dspark起始/四机健康）")
    ap.add_argument("--precheck-hosts", default=",".join(DEFAULT_PRECHECK_HOSTS), help="预检主机列表")
    ap.add_argument("--dry-run", action="store_true", help="只打印计划/校验参数，不发请求")
    args = ap.parse_args()
    if getattr(args, "uuid_prefix", False):
        # W9-R8: 每 run 时间熵 reseed, 跨 run 内容唯一防 APC 命中
        args.random_seed = (args.random_seed * 1000003 + time.time_ns()) % (2**31 - 1)
    if not args.key:
        sys.exit("[fatal] 未提供 API key：请设置 VLLM_API_KEY 环境变量或用 --key 参数")

    # 输出目录（R9）
    if args.out:
        out_dir = args.out
    else:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_dir = os.path.join(args.base_dir, f"BENCHV2_{ts}", args.group)
    os.makedirs(out_dir, exist_ok=True)

    base = args.endpoint.rstrip("/")
    url = base + "/chat/completions"
    headers = {"Authorization": f"Bearer {args.key}", "Content-Type": "application/json"}
    if args.metrics_url:
        metrics_url = args.metrics_url
    elif base.endswith("/v1"):
        metrics_url = base[:-3] + "/metrics"
    else:
        metrics_url = ""
    if not metrics_url:
        sys.exit("[fatal] 无法推导 /metrics 地址，请用 --metrics-url 显式指定")

    try:
        import requests  # noqa: F401
    except ImportError:
        sys.exit("[fatal] 需要 requests：pip install requests")

    session = requests.Session()

    # 就绪自检 + 校准（dry-run 跳过实际请求）
    models = []
    if not args.dry_run:
        try:
            mr = session.get(base + "/models", headers=headers, timeout=(10, 30))
            mr.raise_for_status()
            models = [m["id"] for m in mr.json().get("data", [])]
            print(f"[ready] models={models}", flush=True)
            if args.model not in models:
                print(f"[warn] --model '{args.model}' 不在 served 列表，尝试选第一个", flush=True)
                if models:
                    args.model = models[0]
        except Exception as e:  # noqa: BLE001
            sys.exit(f"[fatal] /v1/models 不可达：{e}")
        try:
            tpu = calibrate(session, url, headers, args.model, args.request_timeout, args.connect_timeout)
        except Exception as e:  # noqa: BLE001
            sys.exit(f"[fatal] 校准失败：{e}")
    else:
        tpu = 1.0
        print("[dry-run] 跳过 /v1/models 与校准（不发请求）", flush=True)

    plan = build_plan(args, tpu)
    print(f"[plan] group={args.group} run_type={args.run_type} conc={parse_list(args.concurrency)} "
          f"tiers={len(plan)} rounds={args.rounds} cooldown={args.cooldown}s seed_base={args.random_seed} "
          f"monitor_interval={args.monitor_interval}s engine={ENGINE} ignore_eos_de={not args.no_ignore_eos}", flush=True)
    for p in plan:
        tag = "DE" if p["mode"] == "de" else "PR"
        if p["mode"] == "de":
            print(f"  - {tag} task={p['task_type']:<6} input={p['input_len']} out={p['output_len']} "
                  f"conc={p['concurrency']} seed={p['seed']}", flush=True)
        else:
            print(f"  - {tag} prefix={p['prefix_len']:>6} out=1 conc={p['concurrency']} seed={p['seed']}", flush=True)
    if args.dry_run:
        print(f"[dry-run] 计划如上，输出目录={out_dir}，未执行。", flush=True)
        return

    # 输出文件
    csv_path = os.path.join(out_dir, f"rows_{args.group}.csv")
    sum_path = os.path.join(out_dir, f"summary_{args.group}.json")
    mon_path = os.path.join(out_dir, f"monitor_{args.group}.log")
    bench_path = os.path.join(out_dir, f"bench_{args.group}.json")
    manifest_path = os.path.join(out_dir, f"manifest_{args.group}.json")

    signal.signal(signal.SIGTERM, _sig_flush_handler)
    signal.signal(signal.SIGINT, _sig_flush_handler)

    # 预检（可选，R9 precheck；与 --no-monitor 解耦，precheck 自身直接读 /metrics）
    precheck = None
    if args.precheck:
        print("[precheck] 开始批次预检...", flush=True)
        precheck = run_precheck(metrics_url, headers, parse_list(args.precheck_hosts, cast=str))
        m = precheck.get("metrics", {})
        print(f"[precheck] running={m.get('running')} running_zero={m.get('running_zero')} "
              f"dspark_start={m.get('dspark_counters_start', {}).get('drafts_total')}", flush=True)
        if m.get("running_zero") is False:
            print("[warn] 预检 running 非 0，批次隔离性存疑，继续执行（monitor 会逐档判定）", flush=True)
        precheck_path = os.path.join(out_dir, f"precheck_{args.group}.json")
        with open(precheck_path, "w", encoding="utf-8") as f:
            json.dump(precheck, f, ensure_ascii=False, indent=2)

    csv_f = open(csv_path, "w", newline="", encoding="utf-8")
    writer = csv.writer(csv_f)
    _SIG_STATE.update({"csv_f": csv_f, "sum_path": sum_path, "group": args.group})
    writer.writerow([
        "mode", "task_type", "prefix_len", "input_len", "output_len", "concurrency", "wave",
        "ok", "status", "prompt_tokens", "completion_tokens",
        "ttft_s", "total_s", "prefill_tps", "decode_tps", "err",
    ])
    mon_f = open(mon_path, "w", encoding="utf-8")
    mon_w = csv.writer(mon_f)
    mon_w.writerow(["tier", "mode", "task_or_prefix", "concurrency", "ts_iso", "ts_epoch", "running", "expected_c"])

    summaries = []
    _SIG_STATE["summaries"] = summaries
    batch_start_iso = iso_now()
    batch_t0 = time.time()

    try:
        total = len(plan)
        for idx, cfg in enumerate(plan, 1):
            stream = SeededPromptStream(cfg["seed"], tpu, task=cfg.get("task_type"))
            tag = f"[{idx}/{total}] " + ("DE" if cfg["mode"] == "de" else "PR")
            if cfg["mode"] == "de":
                tag += f" task={cfg['task_type']:<6} conc={cfg['concurrency']}"
            else:
                tag += f" prefix={cfg['prefix_len']:>6} conc={cfg['concurrency']}"
            print(f"{tag} start", flush=True)

            monitor = None
            if not args.no_monitor:
                monitor = Monitor(metrics_url, headers, args.monitor_interval,
                                  cfg["concurrency"], tag)
                monitor.start()
                time.sleep(args.monitor_interval * BASELINE_SAMPLES)   # baseline（running 回落 0）

            snap_start = read_metrics(metrics_url, headers) if not args.no_monitor else None   # dspark 起始（R5）

            t_start = time.time()
            t_start_iso = iso_now()
            all_results = []
            for w in range(1, args.rounds + 1):
                results = run_wave(stream, session, url, headers, args.model,
                                   cfg.get("input_len", cfg.get("prefix_len")),
                                   cfg["max_tokens"], cfg["concurrency"],
                                   args.request_timeout, args.connect_timeout,
                                   cfg["ignore_eos"] and not args.no_ignore_eos)
                all_results.extend(results)
                write_rows(writer, results, cfg, w)
                csv_f.flush()
            t_end = time.time()
            t_end_iso = iso_now()
            elapsed = round(t_end - t_start, 1)

            snap_end = read_metrics(metrics_url, headers) if not args.no_monitor else None     # dspark 结束（R5）

            monitor_stats = None
            if monitor is not None:
                time.sleep(args.monitor_interval * 2)          # post 采样：确认 running 回落 0
                monitor.stop()
                for ts, val in monitor.samples:
                    mon_w.writerow([idx, cfg["mode"],
                                    cfg.get("task_type", "") or cfg.get("prefix_len", ""),
                                    cfg["concurrency"],
                                    datetime.fromtimestamp(ts).astimezone().isoformat(timespec="seconds"),
                                    round(ts, 3), "" if val is None else val, cfg["concurrency"]])
                mon_f.flush()
                monitor_stats = monitor.classify(t_start, t_end)
                if monitor_stats["pure_running_eq_c"]:
                    pmsg = "PURE(running==C)"
                elif monitor_stats["reached_full_concurrency"]:
                    pmsg = f"PARTIAL(reached C={cfg['concurrency']} but overshoot/too few at-C)"
                elif monitor_stats["purity_confidence"] == "low":
                    pmsg = f"INCONCLUSIVE(fast tier, during samples={monitor_stats['n_during_samples']} < 3, 无法确认 running==C)"
                else:
                    pmsg = f"IMPOLLUTED/running never reached C={cfg['concurrency']} (max={monitor_stats['during']['max']})"
                print(f"{tag} monitor: {pmsg} (during samples={monitor_stats['n_during_samples']}, "
                      f"at_C={monitor_stats['n_during_at_c']})", flush=True)

            dspark = dspark_stats(snap_start, snap_end, len(all_results)) if not args.no_monitor else None
            if dspark and dspark.get("available"):
                print(f"{tag} dspark: accept_rate={dspark.get('dspark_accept_rate')} "
                      f"per_pos={dspark.get('dspark_per_pos_accept')} "
                      f"draft/req={dspark.get('dspark_draft_per_request')}", flush=True)

            meta = {
                "mode": cfg["mode"], "task_type": cfg.get("task_type"), "prefix_len": cfg.get("prefix_len"),
                "input_len": cfg.get("input_len"), "output_len": cfg.get("output_len"),
                "concurrency": cfg["concurrency"], "max_tokens": cfg["max_tokens"], "seed": cfg["seed"],
                "rounds": args.rounds, "engine": ENGINE, "ignore_eos": cfg["ignore_eos"] and not args.no_ignore_eos,
                "start_ts": t_start_iso, "end_ts": t_end_iso,
                "elapsed_s": elapsed, "monitor": monitor_stats, "dspark": dspark,
            }
            s = summarize_tier(all_results, meta)
            summaries.append(s)
            print(f"{tag} done {elapsed}s | accept={s['acceptance_rate']} ok={s['requests_ok']}/{s['requests_total']} "
                  f"prefill_p50={s.get('p50_prefill_tps')} decode_p50={s.get('p50_decode_tps')} "
                  f"ttft_p50={s.get('p50_ttft_s')} ct_p50={s.get('p50_completion_tokens')}", flush=True)

            if idx < total and args.cooldown > 0:
                print(f"  ...cooldown {args.cooldown}s", flush=True)
                time.sleep(args.cooldown)
    finally:
        csv_f.close()
        mon_f.close()

    with open(sum_path, "w", encoding="utf-8") as f:
        json.dump({"group": args.group, "model": args.model, "endpoint": args.endpoint,
                   "engine": ENGINE, "summary": summaries}, f, ensure_ascii=False, indent=2)

    # bench 配置快照（R9）
    bench_cfg = {
        "group": args.group, "endpoint": args.endpoint, "model": args.model,
        "run_type": args.run_type, "concurrency": parse_list(args.concurrency),
        "task_type": args.task_type, "input_len": args.input_len, "output_len": args.output_len,
        "prefix_len": args.prefix_len, "rounds": args.rounds, "random_seed": args.random_seed,
        "engine": ENGINE, "temperature": TEMPERATURE,
        "ignore_eos_de": not args.no_ignore_eos,
        "cooldown_s": args.cooldown, "request_timeout_s": args.request_timeout,
        "monitor_interval_s": args.monitor_interval, "metrics_url": metrics_url,
        "served_models": models, "dry_run": False,
    }
    with open(bench_path, "w", encoding="utf-8") as f:
        json.dump(bench_cfg, f, ensure_ascii=False, indent=2)

    # 批次 manifest（R7）
    batch_end_iso = iso_now()
    manifest = {
        "group": args.group, "endpoint": args.endpoint, "model": args.model,
        "engine": ENGINE, "temperature": TEMPERATURE, "rounds": args.rounds,
        "random_seed": args.random_seed, "run_type": args.run_type,
        "start_ts": batch_start_iso, "end_ts": batch_end_iso,
        "total_elapsed_s": round(time.time() - batch_t0, 1),
        "n_tiers": len(summaries),
        "tiers": [{
            "mode": s["mode"],
            "task_type": s.get("task_type"),
            "prefix_len": s.get("prefix_len"),
            "concurrency": s["concurrency"],
            "max_tokens": s.get("max_tokens"),
            "start_ts": s["start_ts"], "end_ts": s["end_ts"], "elapsed_s": s["elapsed_s"],
            "requests_total": s["requests_total"], "acceptance_rate": s["acceptance_rate"],
            "pure_running_eq_c": (s.get("monitor") or {}).get("pure_running_eq_c"),
            "dspark_accept_rate": (s.get("dspark") or {}).get("dspark_accept_rate"),
            "dspark_per_pos_accept": (s.get("dspark") or {}).get("dspark_per_pos_accept"),
            "dspark_draft_per_request": (s.get("dspark") or {}).get("dspark_draft_per_request"),
            "dspark_counters_start": (s.get("dspark") or {}).get("start"),
            "dspark_counters_end": (s.get("dspark") or {}).get("end"),
        } for s in summaries],
        "environment": {
            "served_models": models,
            "max_model_len_note": "model/max_model_len 以 /v1/models 为准（见 bench_cfg）",
            "precheck": precheck,
        },
    }
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print("\n=== SUMMARY (p50) ===", flush=True)
    print(f"{'mode':<4} {'task/prefix':<14} {'c':>2} | {'accept':>6} {'prefill_tps':>10} {'decode_tps':>10} "
          f"{'ttft_s':>8} {'ct_p50':>8} {'dspark_acc':>9}", flush=True)
    for s in summaries:
        label = s.get("task_type") or str(s.get("prefix_len"))
        da = (s.get("dspark") or {}).get("dspark_accept_rate")
        print(f"{s['mode']:<4} {label:<14} {s['concurrency']:>2} | "
              f"{str(s.get('acceptance_rate')):>6} {str(s.get('p50_prefill_tps')):>10} "
              f"{str(s.get('p50_decode_tps')):>10} {str(s.get('p50_ttft_s')):>8} "
              f"{str(s.get('p50_completion_tokens')):>8} {str(da):>9}", flush=True)
    print(f"\n结果目录：{out_dir}", flush=True)
    print(f"  rows     : {csv_path}", flush=True)
    print(f"  summary  : {sum_path}", flush=True)
    print(f"  monitor  : {mon_path}", flush=True)
    print(f"  bench    : {bench_path}", flush=True)
    print(f"  manifest : {manifest_path}", flush=True)
    if precheck:
        print(f"  precheck : {os.path.join(out_dir, f'precheck_{args.group}.json')}", flush=True)


if __name__ == "__main__":
    main()
