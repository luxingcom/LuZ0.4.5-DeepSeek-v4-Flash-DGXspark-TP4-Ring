#!/bin/bash
# gid_preflight.sh v1.0 — RoCE GID 预检 (W9R15 2026-09-03)
#
# 背景(根因链条, 2026-09-03 督导复盘):
#   对端硬断电 -> 本机直连 RoCE 口链路反复 down/up -> NetworkManager 在链路抖动时
#   撤掉静态 IP 且链路恢复后不自动加回(NM 应用态与配置脱节) -> IB GID index3 变全零
#   -> NCCL 建链必败: rank0 报 "ibv_modify_qp failed with 61 No data available,
#      local GID ::" (GID 为空), remote GID ::ffff:<RING_SUBNET>。
#   全集群审计: 仅 01 两个口有此暗伤, 02/03/04 八口 GID 正常。
#   修复: nmcli device reapply 不够(NM 记账不刷新), 必须 disconnect + connect 硬复位。
#
# 用法:
#   bash gid_preflight.sh            # 只读检查本机全部 rocep* 口 gids/3
#   bash gid_preflight.sh --fix      # 检查 + 对空 GID 口 nmcli disconnect/connect 复位
#   bash gid_preflight.sh --all      # 检查四机(186-189, 经 ssh, 只读)
#   bash gid_preflight.sh --all --fix # 四机检查 + 修复
# 环境: GID_SUDO_PW 提供 sudo 密码(已配 NOPASSWD nmcli 时可省)
# 退出: 0 = 全部口 GID 有效(或已修复); 1 = 仍有异常
#
# 集成点(重建/拉起容器前调用, 空 GID 先复位再拉起, 避免重建死循环):
#   - /opt/_PH_INSTALL_/scripts/healthcheck-rebuild.sh    (docker rm 触发重建前)
#   - ~/_PH_USER_KIT_/monitor_tp4_head_v043.sh                 (start 容器前)
#   - ~/_PH_USER_KIT_/monitor_tp4_worker_v043.sh               (start 容器前)
#
# 诊断口诀: rank0 日志出现 ibv_modify_qp errno 61 = 先查 GID (gids/3 非零),
#           不要误判为 NCCL/驱动问题。

ZERO_RE='^0000:0000:0000:0000:0000:0000:0000:0000$'
DO_FIX=0
ALL=0
for a in "$@"; do
  case "$a" in
    --fix) DO_FIX=1 ;;
    --all) ALL=1 ;;
    -h|--help) grep -E '^# (背景|用法|退出|诊断|集成)' "$0"; exit 0 ;;
    *) echo "未知参数: $a" >&2; exit 2 ;;
  esac
done

NODES=(_PH_HEAD_IP_.186 _PH_HEAD_IP_.187 _PH_HEAD_IP_.188 _PH_HEAD_IP_.189)  # 四机管理网，_PH_HEAD_IP_=管理网前三段（替换后执行）

sudo_nmcli() {
  if [ -n "${GID_SUDO_PW:-}" ]; then
    printf '%s\n' "$GID_SUDO_PW" | sudo -S "$@" 2>/dev/null
  else
    sudo -n "$@" 2>/dev/null
  fi
}

# 检查单个 IB 口 gids/3; 返回 0=有效, 1=空/全零
check_ib() {
  local ib="$1" gid3 netdev
  gid3=$(cat "/sys/class/infiniband/$ib/ports/1/gids/3" 2>/dev/null)
  if [ -z "$gid3" ]; then
    echo "  [EMPTY] $ib gids/3 缺失/不可读 (NCCL_IB_GID_INDEX=3)"
    return 1
  fi
  if printf '%s' "$gid3" | grep -qE "$ZERO_RE"; then
    netdev=$(ls "/sys/class/infiniband/$ib/device/net/" 2>/dev/null | head -1)
    echo "  [ZERO] $ib gids/3 = $gid3 全零 (对端断电残留, netdev=${netdev:-?} 需 nmcli 复位)"
    return 1
  fi
  echo "  [OK]   $ib gids/3 = $gid3"
  return 0
}

# 修复单个 IB 口: nmcli disconnect+connect 硬复位 (NM 记账刷新)
fix_ib() {
  local ib="$1" netdev rc
  netdev=$(ls "/sys/class/infiniband/$ib/device/net/" 2>/dev/null | head -1)
  if [ -z "$netdev" ]; then
    echo "  [FIX-FAIL] $ib 无对应 netdev, 无法自动复位"
    return 1
  fi
  echo "  [FIX] $ib -> $netdev: nmcli disconnect + connect 硬复位"
  sudo_nmcli nmcli device disconnect "$netdev"; sleep 2
  sudo_nmcli nmcli device connect "$netdev"; sleep 6
  if check_ib "$ib"; then echo "  [FIX-OK] $ib 复位后 GID 恢复"; return 0; fi
  echo "  [FIX-FAIL] $ib 复位后 GID 仍异常, 需人工核查 NM/IP"
  return 1
}

preflight_host() {
  local host="$1" rc=0 any_bad=0 ibs
  echo "===== GID 预检: $host ====="
  if [ "$host" = "localhost" ] || [ "$host" = "$(hostname)" ]; then
    ibs=$(ls -d /sys/class/infiniband/rocep*/ 2>/dev/null | xargs -n1 basename 2>/dev/null)
    for ib in $ibs; do
      if ! check_ib "$ib"; then
        any_bad=1
        if [ "$DO_FIX" = "1" ]; then fix_ib "$ib" || rc=1; else rc=1; fi
      fi
    done
  else
    local cmd
    if [ "$DO_FIX" = "1" ]; then
      cmd="GID_SUDO_PW='${GID_SUDO_PW:-}' bash /opt/_PH_INSTALL_/scripts/gid_preflight.sh --fix"
    else
      cmd="bash /opt/_PH_INSTALL_/scripts/gid_preflight.sh"
    fi
    ssh -o BatchMode=yes -o ConnectTimeout=8 _PH_USER_@"$host" "$cmd" 2>/dev/null
    rc=$?
  fi
  if [ "$any_bad" = "1" ] && [ "$DO_FIX" != "1" ]; then
    echo "  => 发现 GID 异常(共 ${any_bad} 个口), 请执行 --fix 复位或人工核查" >&2
  fi
  return $rc
}

# 主流程
RC=0
if [ "$ALL" = "1" ]; then
  for h in "${NODES[@]}"; do
    preflight_host "$h"; R=$?
    [ "$R" != "0" ] && RC=1
  done
else
  preflight_host "$(hostname)"; RC=$?
fi
echo "===== GID 预检完成: $([ "$RC" = "0" ] && echo '全部正常' || echo '存在异常') ====="
exit $RC
