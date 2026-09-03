#!/bin/bash
# gpu-temp-watch.sh v1.0 — GPU 温度巡检 (LuZ0.4.5)
# 背景: 03 号机曾满载过热断电 (93°C 告警线); 自动化温度采集, 对接 gb10-clock-cap 降频联动
# 用法: bash gpu-temp-watch.sh            # 单次采样报告
#       bash gpu-temp-watch.sh --alert 93 # 超阈值输出 WARN + 写状态文件
# 状态: /opt/_PH_INSTALL_/state/temp.<role>.maxc   (供外部采集/monitor)
# 可挂 systemd timer (OnUnitActiveSec=60s)
set -uo pipefail

ALERT="${ALERT_C:=-1}"
ROLE="$(hostname | grep -q node0X && echo head || echo worker)"
STATE_DIR=_PH_INSTALL_DIR_/state
mkdir -p "$STATE_DIR" 2>/dev/null || true

while [ $# -gt 0 ]; do
  case "$1" in
    --alert) ALERT="${2:-}"; shift 2 ;;
    -h|--help) grep -E '^# (用法|背景|状态)' "$0"; exit 0 ;;
    *) echo "未知参数: $1" >&2; exit 2 ;;
  esac
done

# 采样 nvidia-smi 温度
MAXC=0
if command -v nvidia-smi >/dev/null 2>&1; then
  MAXC=$(nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader,nounits 2>/dev/null | sort -n | tail -1)
  MAXC=${MAXC:-0}
fi
echo "$MAXC" > "$STATE_DIR/temp.$ROLE.maxc"
echo "[temp][$ROLE] max_celsius=$MAXC alert=${ALERT}"

if [ "$ALERT" -gt 0 ] && [ "$MAXC" -ge "$ALERT" ]; then
  echo "[temp][$ROLE] WARN: 温度 ${MAXC}°C ≥ ${ALERT}°C 告警线 — 建议 gb10-clock-cap 降频或检查散热" >&2
  exit 1
fi
exit 0
