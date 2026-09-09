#!/bin/bash
# =============================================================
# SCRIPT: crash_dump.sh
# VERSION: v1.0-prod-harden  (2026-08-26)
# ROLE: 崩溃指纹留存 — systemd ExecStopPost 调用
#   见 incident-clone-roce-prevention-2026-08-25.md §分层预防 P0-观测 #2
#   "容器崩溃 ExecStopPost dump docker logs 到持久目录 + dmesg 采集" — 闭合 RCA 缺口
#   (生产四机历史日志已删 = RCA 最大缺口, 崩溃必须自带指纹留存)
# 功能:
#   * dump docker logs <container> 到持久目录  crash-<ts>/
#   * dmesg 采集 NV_ERR / carrier / link flap / IBV 错误 (内核 ring 过滤)
#   * 时间戳目录 crash-<ts>/ (ts = 纳秒时间戳, 便于排序与唯一)
# USAGE:
#   ExecStopPost=/opt/_PH_INSTALL_/scripts/crash_dump.sh vllm-tp4-rank0
#   bash crash_dump.sh [container_name] [--dir /path/to/persistent]
# EXITCODES:
#   0 = 采集完成 (即使容器已删除, 日志部分仍尽力)
#   1 = 参数错误 / 采集目录不可写
# CHANGE: 改脚本须 bash -n + .bak-<tag> 留档 + 更新 REFERENCE.md
# =============================================================
set -uo pipefail

CONTAINER="${1:-}"
# QA-fix C1: 默认持久路径 /opt/_PH_INSTALL_/backup/crash-dumps 必须在持久盘上 (否则崩溃指纹重建后丢失
#   = RCA 缺口未闭合)。用 $CRASH_DUMP_DIR 覆写。下方脚本头做 mount 类型检查并提示。
DUMP_BASE="${CRASH_DUMP_DIR:-/opt/_PH_INSTALL_/backup/crash-dumps}"
[ -n "$CONTAINER" ] || { echo "[crash_dump] 用法: $0 <container> [--dir <base>]" >&2; exit 1; }
shift
while [ $# -gt 0 ]; do
  case "$1" in
    --dir) DUMP_BASE="${2:-}"; shift 2 ;;
    *) shift ;;
  esac
done

TS="$(date +%Y%m%d-%H%M%S-%N)"
DEST="${DUMP_BASE}/crash-${TS}"
mkdir -p "$DEST" 2>/dev/null || { echo "[crash_dump] 无法创建 $DEST" >&2; exit 1; }

echo "[crash_dump] container=$CONTAINER → $DEST"

# --- 1. docker logs (尽力, 守护退出时容器可能已消失) ---
# QA-fix C1: 表头由 `>` 改 `>>`? 否 — 此处首写文件, `>` 正确; 但下方 docker logs 重定向会覆盖,
#   故表头改为 `>>` 追加到已存在/或新建的表头文件, 先确认 DUMP_BASE 在持久盘上。
# --- 1a. 持久化确认: 检查 DUMP_BASE 所在文件系统 mount 类型 (提示而非阻断) ---
if command -v findmnt >/dev/null 2>&1; then
  _mnt=$(findmnt -no FSTYPE "$DUMP_BASE" 2>/dev/null || findmnt -no FSTYPE -T "$DUMP_BASE" 2>/dev/null || echo "?")
  case "$_mnt" in
    tmpfs|overlay) echo "[crash_dump][warn] $DUMP_BASE 落在 $_mnt (非纯持久盘), 崩溃指纹可能在重启/容器重建后丢失 — 建议迁到持久盘" >&2 ;;
    *) echo "[crash_dump] 确认 $DUMP_BASE 文件系统: $_mnt" ;;
  esac
else
  echo "[crash_dump][warn] findmnt 不可用, 未能确认 $DUMP_BASE 是否在持久盘 (请运维人工核对)" >&2
fi
echo "--- docker logs ${CONTAINER} (tail 20000) ---" | tee "$DEST/docker-logs.txt" >/dev/null
if docker logs --tail 20000 "$CONTAINER" >>"$DEST/docker-logs.txt" 2>&1; then
  echo "[crash_dump] docker logs saved ($(wc -l < "$DEST/docker-logs.txt") lines)"
else
  echo "  [warn] docker logs 不可用 (容器可能已删除), 保留已得内容"
fi

# --- 2. docker inspect (容器元数据, 若仍存在) ---
if docker inspect "$CONTAINER" >"$DEST/docker-inspect.json" 2>/dev/null; then
  echo "[crash_dump] docker inspect saved"
else
  rm -f "$DEST/docker-inspect.json"
fi

# --- 3. dmesg 采集 — NCCL/RoCE/carrier/IBV 关键指纹 ---
DMESG_OK=0
# P0-FORENSICS-FIX 2026-08-31: 三级降级取内核 ring (systemd 以 User=_PH_USER_ 运行, dmesg 需 root)
if dmesg -T > "$DEST/dmesg-full.txt" 2>/dev/null && [ -s "$DEST/dmesg-full.txt" ]; then
  DMESG_OK=1
elif command -v sudo >/dev/null 2>&1 && sudo -n dmesg -T > "$DEST/dmesg-full.txt" 2>/dev/null && [ -s "$DEST/dmesg-full.txt" ]; then
  DMESG_OK=1
elif journalctl -k -b --no-pager > "$DEST/dmesg-full.txt" 2>/dev/null && [ -s "$DEST/dmesg-full.txt" ]; then
  DMESG_OK=1
else
  : > "$DEST/dmesg-full.txt"
fi
if [ "$DMESG_OK" = "1" ]; then
  {
    echo "=== 过滤: NV_ERR / 载波 / flap / IB / IBV / QP / retry / link ==="
    grep -iE 'NV_ERR|NV_MEM|cudaMemo|carrier|link.*(down|flap|change)|ibv_|ib_dev|IBQP|modify_qp|retry.*exc|RDMA|roce|mlx5|ConnectX|link_down|enP7|roceP|card ' "$DEST/dmesg-full.txt" 2>/dev/null \
      | tail -500
  } > "$DEST/dmesg-roce-filtered.txt" 2>/dev/null
  echo "[crash_dump] dmesg full+filtered saved"
  # P0-FORENSICS-FIX: Xid / NVRM / NV_ERR / OOM 专项汇总 (GPU 故障首查项)
  {
    echo "=== Xid / NVRM / NV_ERR / Out of memory 汇总 (最近 500 条) ==="
    grep -iE 'Xid|NVRM|NV_ERR|NV_MEM|Out of memory|memdescAlloc' "$DEST/dmesg-full.txt" 2>/dev/null | tail -500
  } > "$DEST/dmesg-xid-nvrm.txt" 2>/dev/null
  echo "[crash_dump] dmesg xid-nvrm summary saved"
else
  echo "[warn] dmesg 不可读 (需 root/CAP_SYSLOG), 跳过内核 ring" >&2
fi

# --- 4. 崩溃上下文: 退出时间 / 存活时长 ---
{
  echo "dump_ts=$(date -Iseconds)"
  echo "container=$CONTAINER"
  if docker inspect -f '{{.State.StartedAt}}|{{.State.FinishedAt}}|{{.State.ExitCode}}|{{.State.OOMKilled}}' "$CONTAINER" 2>/dev/null; then :; fi
} > "$DEST/context.txt" 2>/dev/null

# --- 5. 可读摘要 ---
echo "[crash_dump] 崩溃指纹已留存于 $DEST"
echo "[crash_dump] 收集: docker-logs | docker-inspect | dmesg-full(+roce-filtered) | context"
exit 0