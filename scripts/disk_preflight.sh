#!/bin/bash
# disk_preflight.sh — 四机磁盘容量巡检（P3: 187 磁盘 57% 纳入监控）
# 用法: bash disk_preflight.sh [--all] [--threshold 80]
#   --all        巡检四机（186 为主控，SSH 到 worker）
#   --threshold N 告警阈值百分比（默认 80）
# 退出码: 0=全部正常  1=存在超阈值或错误
# 参考文档: docs/ops/roce-gid-preflight-2026-09-03.md（同族运维巡检）
set -u
THRESHOLD=80
ALL=0
for a in "$@"; do
  case "$a" in
    --all) ALL=1 ;;
    --threshold) shift; THRESHOLD=$1 ;;
  esac
done

check_one() {
  local host=$1
  local line
  line=$(ssh -o ConnectTimeout=8 -o BatchMode=yes _PH_USER_@$host "df -h / | tail -1" 2>/dev/null)
  if [ -z "$line" ]; then
    echo "[ERR] $host: SSH/df 失败"
    return 1
  fi
  # 提取使用率百分比（如 57%）
  local pct use avail size
  pct=$(echo "$line" | awk '{print $5}' | tr -d '%')
  size=$(echo "$line" | awk '{print $2}')
  use=$(echo "$line" | awk '{print $3}')
  avail=$(echo "$line" | awk '{print $4}')
  if [ "$pct" -ge "$THRESHOLD" ]; then
    echo "[WARN] $host: 使用率 ${pct}% (${use}/${size}, avail ${avail}) >= 阈值 ${THRESHOLD}%"
    return 1
  else
    echo "[OK]   $host: 使用率 ${pct}% (${use}/${size}, avail ${avail})"
    return 0
  fi
}

RC=0
if [ "$ALL" = "1" ]; then
  for h in 186 187 188 189; do
    check_one "_PH_HEAD_IP_.$h" || RC=1
  done
else
  # 本机模式
  host=$(hostname -I 2>/dev/null | awk '{print $1}')
  check_one "$host" || RC=1
fi

echo "DISK_PREFLIGHT_RC=$RC (0=正常, 1=超阈值/错误; 阈值 ${THRESHOLD}%)"
exit $RC
