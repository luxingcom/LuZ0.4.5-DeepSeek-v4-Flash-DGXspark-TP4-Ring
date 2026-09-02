#!/bin/bash
# =============================================================
# SCRIPT: watchdog_hardened.sh
# VERSION: v1.0-prod-harden  (2026-08-26)
# ROLE: NCCL/RoCE 运行时看门狗 (加固版) — 四机通用, 常驻或 cron
#   见 incident-clone-roce-prevention-2026-08-25.md §分层预防 P0-观测 #4
#   "看门狗阈值改『加载期/运行期分段 + 单位时间 NV_ERR 新增速率』窗口, 弃纯累计阈值
#    (flap 卡死期 NV_ERR=0, 纯累计必失效)"
# 加固点 (相对纯累计阈值旧看门狗):
#   a. 加载期/运行期分段: 看门狗启动 <LOADING_WIN 视为加载期, 用更宽容错 (权重加载
#      NV_ERR 可密集但短促); 之后运行期用严格速率阈值。
#   b. 单位时间 NV_ERR 新增速率: 维护 NV_ERR 计数状态文件, 计算上窗口增量, 弃纯累计。
#   c. carrier flap 计数探针 (补盲区): 卡死期 NV_ERR=0 也能探测。通过 ethtool -S
#      采样 link_down_events / crc / rx_err 增量, 及 dmesg link/carrier 事件速率,
#      高于阈值 → 判定物理层威胁 (flap 前兆)。
# USAGE:
#   bash watchdog_hardened.sh [--role head|worker] [--container NAME]
#                             [--state-dir DIR] [--errs-window N] [--flap-window N]
#   (常驻: 由 systemd timer 或 cron 每 60s 调用; 也可 while loop 内置)
# EXITCODES:
#   0 = 健康 (无异常)
#   1 = 发现错误/威胁 (应触发重建/告警)
#   2 = 用法错误
# CHANGE: 改脚本须 bash -n + .bak-<tag> 留档 + 更新 REFERENCE.md
# =============================================================
set -uo pipefail
export HOME=/home/_PH_USER_

ROLE=""
CONTAINER=""
STATE_DIR="${WATCHDOG_STATE_DIR:-/var/lib/tp4-watchdog}"
# 加载期窗口 (秒): 看门狗进程/容器刚起阶段
LOADING_WIN=300
# 运行期每窗口允许新增 NV_ERR 数
ERR_WINDOW=${WATCHDOG_ERR_WINDOW:-2}
# carrier flap 每窗口允许新增 link_down 事件数 (跑 60s 窗口)
FLAP_WINDOW=${WATCHDOG_FLAP_WINDOW:-3}
# 采样间隔
SLEEP_SEC=${WATCHDOG_SLEEP_SEC:-60}

while [ $# -gt 0 ]; do
  case "$1" in
    --role) ROLE="${2:-}"; shift 2 ;;
    --container) CONTAINER="${2:-}"; shift 2 ;;
    --state-dir) STATE_DIR="${2:-}"; shift 2 ;;
    --errs-window) ERR_WINDOW="${2:-2}"; shift 2 ;;
    --flap-window) FLAP_WINDOW="${2:-3}"; shift 2 ;;
    -h|--help) grep -E '^# (USAGE|EXITCODES|ROLE|VERSION)' "$0"; exit 0 ;;
    *) echo "未知参数: $1" >&2; exit 2 ;;
  esac
done

mkdir -p "$STATE_DIR" 2>/dev/null || { echo "[watchdog] 无法创建 $STATE_DIR" >&2; exit 2; }
STATE_NVERR="$STATE_DIR/nv_err_count"
STATE_FLAP="$STATE_DIR/flap_count"

# 判定加载期 vs 运行期
STATE_START="$STATE_DIR/started_at"
[ -f "$STATE_START" ] || echo "$(date +%s)" > "$STATE_START"
NOW_START=$(cat "$STATE_START")
UPTIME=$(( $(date +%s) - NOW_START ))
if [ "$UPTIME" -lt "$LOADING_WIN" ]; then
  PHASE="loading"; ERR_THRESH=$(( ERR_WINDOW * 3 ))   # 加载期 3x 宽容
else
  PHASE="runtime"; ERR_THRESH="$ERR_WINDOW"
fi
echo "[watchdog] phase=$PHASE (uptime ${UPTIME}s)  err_thresh=${ERR_THRESH}"

FAIL=0
if [ -n "$CONTAINER" ]; then
  NAME="$CONTAINER"
else
  # 自动选择本机容器
  if [ -n "$ROLE" ] && [ "$ROLE" = "head" ]; then NAME=vllm-tp4-rank0;
  else NAME=$(docker ps --format '{{.Names}}' | grep -E '^vllm-tp4-rank[0-9]$' | head -1 || echo ""); fi
fi
[ -n "${NAME:-}" ] || { echo "[watchdog] 未找到容器 (可 --container 显式指定)" >&2; exit 2; }

# --- 1. 单位时间 NV_ERR 新增速率 (容器日志) ---
# QA-fix W1: 原实现 `docker logs --since "${LOADING_WIN}s"` 返回的是窗口内计数,
#   却与累计值 LAST_NV 求差 → NEW_ERR≈0 恒不触发 → 卡死期 NV_ERR 新增静默失效。
#   修复(方案a): 去掉 --since, 用容器全量累计行数 CUR_NV 与 LAST_NV 求增量
#   (状态文件存上次累计)。速率语义: 每采样间隔(SLEEP_SEC)内容器新增的 NV_ERR 行数,
#   即"单位时间 NV_ERR 新增速率"。加载期/运行期分段阈值用 UPTIME/ERR_THRESH 判定。
LAST_NV=$(cat "$STATE_NVERR" 2>/dev/null || echo 0)
CUR_NV=$(docker logs "$NAME" 2>&1 | grep -c 'NV_ERR\|NV_MEM\|cudaError\|CUBLAS_STATUS\|ncclSystemError\|DistStoreError\|IBV_WC_RETRY_EXC_ERR' || true)
# 计算本窗增量 (基于全量累计额差); 首窗 LAST_NV=0 → NEW_ERR 为容器全部历史计数
if [ -z "${LAST_NV:-}" ]; then LAST_NV="$CUR_NV"; fi
NEW_ERR=$(( CUR_NV - LAST_NV ))
[ "$NEW_ERR" -lt 0 ] && NEW_ERR=0
echo "[watchdog] NV_ERR 计数: cur=$CUR_NV last=$LAST_NV new=${NEW_ERR} (window ${LOADING_WIN}s)"
echo "$CUR_NV" > "$STATE_NVERR"

if [ "$NEW_ERR" -gt "$ERR_THRESH" ]; then
  echo "[watchdog][${PHASE}] x NV_ERR 新增速率超阈值: ${NEW_ERR} > ${ERR_THRESH}"
  FAIL=1
else
  echo "[watchdog][${PHASE}] ok NV_ERR 速率正常 (${NEW_ERR} ≤ ${ERR_THRESH})"
fi

# --- 2. carrier flap 计数探针 (补 NV_ERR=0 盲区) ---
# 通过 ethtool -S 采样 link_down_events / crc / rx_err 增量 (if present)
FLAP_NEW=0
if command -v ethtool >/dev/null 2>&1; then
  # 采样并统计 link 相关计数 (累计), 状态文件存上次
  LAST_FLAP=$(cat "$STATE_FLAP" 2>/dev/null || echo 0)
  CUR_FLAP=0
  for nic in /sys/class/net/*; do
    nic=${nic##*/}
    case "$nic" in enP7s7|roceP2p1s0f0|roceP2p1s0f1|rocep1s0f0|rocep1s0f1|*eth*) ;;
      *) continue ;;
    esac
    out=$(ethtool -S "$nic" 2>/dev/null | grep -iE 'link_down_events|link_down_events_phy|crc.*err|rx_error|tx_error' || true)
    # 仅计入可解析数值行
    while IFS= read -r line; do
      n=$(echo "$line" | awk '{print $NF}' | grep -E '^[0-9]+$' || echo 0)
      CUR_FLAP=$(( CUR_FLAP + n ))
    done <<< "$out"
  done
  if [ -z "${LAST_FLAP:-}" ]; then LAST_FLAP="$CUR_FLAP"; fi
  FLAP_NEW=$(( CUR_FLAP - LAST_FLAP ))
  [ "$FLAP_NEW" -lt 0 ] && FLAP_NEW=0
  echo "$CUR_FLAP" > "$STATE_FLAP"
  echo "[watchdog] carrier flap 计数: cur=$CUR_FLAP last=$LAST_FLAP new=${FLAP_NEW}"
else
  echo "[watchdog][warn] ethtool 不可用, 跳过 carrier flap 探针 (若本机有 RoCE 需手动装 ethtool)"
fi

if [ "$FLAP_NEW" -gt "$FLAP_WINDOW" ]; then
  echo "[watchdog][${PHASE}] x carrier flap 速率超阈值: ${FLAP_NEW} > ${FLAP_WINDOW} (物理威胁前兆)"
  FAIL=1
else
  echo "[watchdog][${PHASE}] ok carrier 稳定 (flap ${FLAP_NEW} ≤ ${FLAP_WINDOW})"
fi

# --- 3. dmesg link/carrier 事件速率旁证 (若可读) ---
if dmesg -T >/dev/null 2>&1; then
  LINK_EV=$(dmesg -T 2>/dev/null | grep -icE 'link.*(down|flap|state change to down)|carrier' || true)
  echo "[watchdog][${PHASE}] dmesg link/carrier 事件(累计) ${LINK_EV}"
  # 仅记录, 主判据用 ethtool 增量 (dmesg 无时间窗增量)
else
  echo "[watchdog][info] dmesg 不可读, 跳过"
fi

# --- 4. 入口网关 concurrency-proxy 探活 (仅 head; 自愈 + 告警) ---
# 2026-08-26 R12 补盲: 01:18 proxy bind 失败 exit1 后无自愈, 8001 空置 4h+ 致网关 502。
#   sudoers NOPASSWD 已授权 (99-concurrency-proxy); 自愈失败 → FAIL=1 告警。
if [ "$ROLE" = "head" ]; then
  if ss -tln 2>/dev/null | grep -q ":8001"; then
    echo "[watchdog][${PHASE}] ok 网关 8001 监听正常"
  else
    echo "[watchdog][${PHASE}] x 网关 8001 未监听 — 尝试拉起 concurrency-proxy.service"
    sudo -n systemctl start concurrency-proxy.service >/dev/null 2>&1
    sleep 2
    if ss -tln 2>/dev/null | grep -q ":8001"; then
      echo "[watchdog][${PHASE}] ok 网关已恢复 (:8001 监听)"
    else
      echo "[watchdog][${PHASE}] x 网关自愈失败 — 请手动: sudo systemctl start concurrency-proxy" >&2
      FAIL=1
    fi
  fi
else
  echo "[watchdog][info] 非 head 角色, 跳过网关探活"
fi

if [ "$FAIL" = "0" ]; then
  echo "[watchdog][${PHASE}] ✅ 健康"
  exit 0
else
  echo "[watchdog][${PHASE}] ❌ 发现异常 (NV_ERR 速率 或 carrier flap), 应触发重建/告警"
  exit 1
fi