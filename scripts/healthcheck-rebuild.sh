#!/bin/bash
# =============================================================
# SCRIPT: healthcheck-rebuild.sh
# VERSION: v1.0-p2
# ROLE: vLLM TP4 主动重建健康检查 (P1) — 四机
# USAGE: bash healthcheck-rebuild.sh [--role head|worker] [--cooldown SEC]
# 原理: 调用 healthcheck.sh 只读探针; 探针失败 => docker rm -f 本机 vllm 容器
#       触发 monitor docker wait 返回 -> exit 1 -> systemd Restart -> 重建
#       (2026-08-17 fix: 原 systemctl restart 只重启 monitor 不重建容器, 已改)
# 保护: --cooldown 冷却窗口 (默认 1800s), 避免重启风暴; 状态记录于
#       _PH_INSTALL_DIR_/state/healthcheck-rebuild.<role>
# 注意: P1 部署留档。是否挂入定时/告警链路由运维决定; 重启演练期间不启用
# EXITCODES: 0=健康或已触发恢复 1=冷却窗口内跳过 2=用法错误
# CHANGE: 改脚本须 bash -n + .bak-<tag> 留档 + 更新 REFERENCE.md
# P2 (2026-08-26): 修复探针误杀——探针失败时先查 8002 HTTP 存活,
#                 存活=繁忙不重建; 8002 不可达时连续 2 次失败才重建; 健康/重建后清零 failcnt
# =============================================================
set -uo pipefail
export HOME=/home/_PH_USER_

ROLE=""
COOLDOWN=1800

while [ $# -gt 0 ]; do
  case "$1" in
    --role) ROLE="${2:-}"; shift 2 ;;
    --cooldown) COOLDOWN="${2:-1800}"; shift 2 ;;
    -h|--help) grep -E '^# (USAGE|EXITCODES|ROLE)' "$0"; exit 0 ;;
    *) echo "未知参数: $1" >&2; exit 2 ;;
  esac
done

if [ -z "$ROLE" ]; then
  if [ "$(hostname)" = "node0X" ]; then ROLE=head; else ROLE=worker; fi
fi

SVC="vllm-tp4-worker.service"
[ "$ROLE" = "head" ] && SVC="vllm-tp4-head.service"
STATE_DIR=_PH_INSTALL_DIR_/state
mkdir -p "$STATE_DIR" 2>/dev/null || true
FAIL_STATE="$STATE_DIR/healthcheck-rebuild.$ROLE.failcnt"

# 1. 先跑只读探针
if bash _PH_INSTALL_DIR_/scripts/healthcheck_hardened.sh --role "$ROLE" --timeout 30 --grace-sec 900; then
  echo "[healthcheck-rebuild][$ROLE] healthy, 无需干预"
  echo 0 > "$FAIL_STATE" 2>/dev/null || true
  exit 0
fi

# 2. 冷却窗口判断 (state 文件存最近触发时间戳)
STATE_DIR=_PH_INSTALL_DIR_/state
mkdir -p "$STATE_DIR" 2>/dev/null || true
STATE="$STATE_DIR/healthcheck-rebuild.$ROLE"
NOW=$(date +%s)
LAST=0
[ -f "$STATE" ] && LAST=$(cat "$STATE" 2>/dev/null || echo 0)
if [ $((NOW - LAST)) -lt "$COOLDOWN" ]; then
  echo "[healthcheck-rebuild][$ROLE] 冷却窗口内 ($((NOW - LAST))s < ${COOLDOWN}s), 跳过触发" >&2
  exit 1
fi

# 2.6 繁忙 vs 卡死判定 (P2): 探针失败但 8002 HTTP 存活 => 高负载繁忙, 不重建
#     (2026-08-26 修复误杀: 131K prefill 长档下探针 30s 超时但引擎仅是繁忙)
if curl -sf -m 5 http://127.0.0.1:8002/health >/dev/null 2>&1; then
  echo "[healthcheck-rebuild][$ROLE] 探针超时但 8002 HTTP 存活 => 繁忙(BUSY)非卡死, 不重建 (P0-观测)"
  exit 0
fi
# 2.7 8002 不可达 => 连续 2 次失败才重建 (防单次抖动误杀)
#     (W9R12 2026-09-02: GPU 利用率旁证准确性低已关闭, 恢复纯 failcnt 判定)
FAIL_NOW=0
[ -f "$FAIL_STATE" ] && FAIL_NOW=$(cat "$FAIL_STATE" 2>/dev/null || echo 0)
FAIL_NOW=$((FAIL_NOW + 1))
echo "$FAIL_NOW" > "$FAIL_STATE"
if [ "$FAIL_NOW" -lt 2 ]; then
  echo "[healthcheck-rebuild][$ROLE] 8002 不可达 failcnt=${FAIL_NOW}/2, 仅观测不重建 (P0-观测)"
  exit 0
fi

# 3. 触发主动重建: docker rm -f 本机 vllm 容器
#    (monitor 的 docker wait 返回 -> exit 1 -> systemd Restart -> monitor 重建容器)
echo "$NOW" > "$STATE"
echo "[healthcheck-rebuild][$ROLE] 探针失败, 触发主动重建: docker rm -f 本机 vllm028-tp4-rank*"
echo 0 > "$FAIL_STATE" 2>/dev/null || true
docker rm -f $(docker ps -aq --filter name=vllm028-tp4-rank) 2>/dev/null || true
echo "[healthcheck-rebuild][$ROLE] 已触发容器重建, systemd 自愈接管"
exit 0
