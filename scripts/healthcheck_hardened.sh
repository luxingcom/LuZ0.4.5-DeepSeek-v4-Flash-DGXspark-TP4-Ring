#!/bin/bash
# =============================================================
# SCRIPT: healthcheck_hardened.sh
# VERSION: v1.0-prod-harden  (2026-08-26)  — 派生自 healthcheck.sh v1.1-p3
# ROLE: vLLM TP4 只读健康探针 (P0, 加固版) — 四机通用
#   见 incident-clone-roce-prevention-2026-08-25.md §分层预防 P0-观测 #3
#   "守卫加推理活性探针 (闭合卡死 100s+ 仍判 healthy 盲区) + 冷启动宽限保留"
# 相比 healthcheck.sh 的新增:
#   * 推理活性探针: 对 head 发带超时的极小生成请求 (prompt 极小, max_tokens=1),
#     判定是否卡死 (卡死 = HTTP 无响应超时 或 flow 停滞)。闭合现有 healthcheck.sh
#     只查容器 running + 8001 /health 的盲区 — 引擎可 /health=200 但 NCCL comm 已死。
#   * 冷启动宽限 (900s) HOLD: 宽限期内且引擎就绪标记未现 → skip 活性探针, 不误杀。
#   * 探针在宽限结束或就绪标记出现后进入"加载期/运行期"判定:
#       加载期 (就绪标记刚现 <LOADING_WIN): 活性探针且宽松超时, 防 prefill 抖动误杀;
#       运行期: 严格超时。
# 只读: 仅探测输出状态, 不执行恢复 (重建由 monitor/systemd 负责)。
# USAGE: bash healthcheck_hardened.sh [--role head|worker] [--timeout SEC]
#                                    [--grace-sec SEC] [--api-key KEY]
# EXITCODES: 0=healthy 1=unhealthy 2=用法错误
# CHANGE: 改脚本须 bash -n + .bak-<tag> 留档 + 更新 REFERENCE.md
# =============================================================
set -uo pipefail
export HOME=/home/_PH_USER_

ROLE=""
TIMEOUT=10
GRACE_SECONDS="${GRACE_SECONDS:-900}"
# 加载期窗口: 就绪后若干秒, 活性探针用宽松超时 (防 prefill 冷启动抖动)
LOADING_WIN=120
LOADING_TIMEOUT=25
PROBE_API_KEY="${VLLM_API_KEY:-}"

while [ $# -gt 0 ]; do
  case "$1" in
    --role) ROLE="${2:-}"; shift 2 ;;
    --timeout) TIMEOUT="${2:-10}"; shift 2 ;;
    --grace-sec) GRACE_SECONDS="${2:-900}"; shift 2 ;;
    --api-key) PROBE_API_KEY="${2:-}"; shift 2 ;;
    -h|--help) grep -E '^# (USAGE|EXITCODES|ROLE|VERSION)' "$0"; exit 0 ;;
    *) echo "未知参数: $1" >&2; exit 2 ;;
  esac
done

NAME=""
if [ -z "$ROLE" ]; then
  if docker ps --format '{{.Names}}' | grep -qx 'vllm028-tp4-rank0'; then
    ROLE=head; NAME=vllm028-tp4-rank0
  elif docker ps --format '{{.Names}}' | grep -qE '^vllm028-tp4-rank[1-3]$'; then
    ROLE=worker; NAME=$(docker ps --format '{{.Names}}' | grep -E '^vllm028-tp4-rank[1-3]$' | head -1)
  else
    echo "[healthcheck-hard][${ROLE:-?}] 未找到 vllm028-tp4-rank* 容器 (本机非 TP4 成员或服务未拉起)"
    exit 1
  fi
else
  case "$ROLE" in
    head)   NAME=vllm028-tp4-rank0 ;;
    worker) NAME=$(docker ps --format '{{.Names}}' | grep -E '^vllm028-tp4-rank[1-3]$' | head -1) ;;
    *) echo "role 必须是 head|worker" >&2; exit 2 ;;
  esac
fi

FAIL=0

# --- 1. 容器存在且 running ---
if ! docker ps --filter "name=^${NAME}$" --format '{{.Names}}' | grep -qx "$NAME"; then
  echo "[healthcheck-hard][${ROLE}] x 容器 ${NAME} 不存在或未运行"
  exit 1   # 硬故障: 不受宽限保护
fi
echo "[healthcheck-hard][${ROLE}] ok 容器 ${NAME} 运行中: $(docker ps --filter "name=^${NAME}$" --format '{{.Status}}')"

# --- 冷启动宽限判定 (仅 head) ---
GRACE_ACTIVE=0
UPTIME=0; START_EPOCH=0
if [ "$ROLE" = "head" ]; then
  STARTED_AT=$(docker inspect -f '{{.State.StartedAt}}' "$NAME" 2>/dev/null)
  if [ -n "$STARTED_AT" ]; then
    START_EPOCH=$(date -d "$STARTED_AT" +%s 2>/dev/null || echo 0)
    UPTIME=$(( $(date +%s) - START_EPOCH ))
    if [ "$START_EPOCH" -gt 0 ] && [ "$UPTIME" -lt "$GRACE_SECONDS" ]; then
      if docker logs "$NAME" 2>/dev/null | grep -q "Application startup complete"; then
        echo "[healthcheck-hard][head] ok 就绪标记已出现 (uptime ${UPTIME}s), 提前结束宽限"
      else
        echo "[healthcheck-hard][head] ok 冷启动宽限中 (uptime ${UPTIME}s < ${GRACE_SECONDS}s), skip 探针 (P0-观测)"
        GRACE_ACTIVE=1
      fi
    elif [ "$START_EPOCH" -gt 0 ]; then
      # 宽限已过且就绪标记未现 → 进度式存活: 引擎日志仍在推进则视为初始化中 (2026-09-01 修复)
      # 反例: rank 缺失/分布式阻塞时引擎日志停更 → 无推进 → 交重建判定, 不无限等待
      if ! docker logs "$NAME" 2>/dev/null | grep -q "Application startup complete"; then
        RECENT=$(docker logs "$NAME" --since 300s 2>/dev/null | wc -l)
        if [ "${RECENT:-0}" -gt 0 ]; then
          echo "[healthcheck-hard][head] ok 宽限已过但引擎日志推进中 (uptime ${UPTIME}s, 近300s ${RECENT}行) → 判定初始化中, 不干预 (P0-观测)"
          GRACE_ACTIVE=1
        else
          echo "[healthcheck-hard][head] x 宽限已过且引擎近300s无日志推进 → 疑似卡死, 交重建判定"
        fi
      fi
    fi
  fi
fi

if [ "$GRACE_ACTIVE" = "1" ]; then
  exit 0  # 宽限中 → healthy
fi

# --- 2. head: /health + 推理活性探针 ---
if [ "$ROLE" = "head" ]; then
  # 2a. /health (基础)
  if curl -sf -m "$TIMEOUT" http://127.0.0.1:8001/health >/dev/null 2>&1; then
    echo "[healthcheck-hard][head] ok 8001 /health 正常"
  else
    echo "[healthcheck-hard][head] x 8001 /health 不可用"
    FAIL=1
  fi

  # 2b. 推理活性探针 — 仅 /health OK 时才有意义; 否则已被判失败
  if [ "$FAIL" = "0" ]; then
    # 加载期 vs 运行期超时
    PROBE_TO="$TIMEOUT"
    if [ "$UPTIME" -lt "$LOADING_WIN" ]; then PROBE_TO="$LOADING_TIMEOUT"; fi
    echo "[healthcheck-hard][head] 推理活性探针 (max_tokens=1, timeout ${PROBE_TO}s)"

    AUTH_ARGS=()
    [ -n "$PROBE_API_KEY" ] && AUTH_ARGS=(-H "Authorization: Bearer ${PROBE_API_KEY}")

    # QA-fix H1: 原硬编码 model "deepseek-v4-flash-0731" → 模型改名后探针 400。改由
    #   SERVED_MODEL_NAME env 注入 (缺省用当前生产名), 使变名后探针仍命中正确模型名。
    SERVED_MODEL_NAME="${SERVED_MODEL_NAME:-deepseek-v4-flash-0731}"
    BODY=$(printf '{"model":"%s","prompt":"ping","max_tokens":1,"stream":false}' "$SERVED_MODEL_NAME")
    OUT=$(curl -sf -m "$PROBE_TO" "${AUTH_ARGS[@]}" \
            -H 'Content-Type: application/json' \
            -d "$BODY" \
            http://127.0.0.1:8001/v1/completions 2>&1)
    RC=$?
    if [ "$RC" = "0" ] && echo "$OUT" | grep -q '"text"'; then
      echo "[healthcheck-hard][head] ok 推理活性正常 (生成返回)"
    else
      # 区分超时(卡死) 与 4xx/5xx
      TIME_HIT=0
      case "$OUT" in *"timeout"*|*"timed out"*) TIME_HIT=1 ;; esac
      if [ "$TIME_HIT" = "1" ] || [ "$RC" != "0" ]; then
        echo "[healthcheck-hard][head] x 推理活性探针超时/失败 (rc=$RC) → 疑似卡死 (闭合 卡死仍 healthy 盲区)"
        echo "  body_rc=$RC"
      else
        echo "[healthcheck-hard][head] x 推理活性探针请求失败: $OUT"
      fi
      # W9R12 (2026-09-02 督导指令): GPU 利用率旁证准确性低, 已关闭 —
      # 探针失败一律判失败, 交重建判定 (长上下文防护由日志活性 300s + 健康检查超时窗承担)
      FAIL=1
    fi
  fi
fi

# --- 3. worker: 仅容器 running (无对外 HTTP), 可选 dmesg 卡死旁证 ---
if [ "$ROLE" = "worker" ]; then
  echo "[healthcheck-hard][worker] ok 容器 running (workers 无对外 HTTP 探针)"
fi

exit "$FAIL"