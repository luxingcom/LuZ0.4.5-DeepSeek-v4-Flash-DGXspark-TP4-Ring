#!/bin/bash
# =============================================================
# Responses API Gateway 兼容入口脚本 (v1.3.0, systemd 托管版)
# - 日常运维统一走 systemctl --user restart responses-gateway
# - 本脚本仅作兼容入口, 内部调用 systemctl, 不再直接拉起 python
# - 移除原 pkill 逻辑: 避免误杀 systemd 托管的同命令行进程 / embed-qwen3-gpu
# - 原 nohup 版备份: start_gateway.sh.bak.nohup
# 负责人: 工程保障团队 SRE 雷克斯 | 2026-08-03
# =============================================================
set -euo pipefail

UNIT="responses-gateway"
PORT="${GATEWAY_PORT:-8003}"

echo "[i] 网关已由 systemd 托管 (${UNIT}.service), 本脚本为兼容入口。"
echo "[i] 执行: systemctl --user restart ${UNIT}"

# 前置检查: 用户 systemd 实例可用
if ! systemctl --user is-system-running >/dev/null 2>&1; then
    # is-system-running 在用户实例下可能返回 degraded/unknown, 仅作提示不阻断
    echo "[w] systemctl --user 状态: $(systemctl --user is-system-running 2>&1 || true)"
fi

# 重启由 systemd 管理 (Restart=always 由单元负责)
systemctl --user restart "${UNIT}"

# 等待单元进入 active (running)
for i in $(seq 1 30); do
    state=$(systemctl --user show -p ActiveState --value "${UNIT}" 2>/dev/null || true)
    sub=$(systemctl --user show -p SubState --value "${UNIT}" 2>/dev/null || true)
    if [ "${state}" = "active" ] && [ "${sub}" = "running" ]; then
        echo "[i] 单元 active/running (第 ${i} 次探测)"
        break
    fi
    sleep 1
done

# 健康检查 (带重试: uvicorn bind 晚于 systemd active)
echo "[i] 健康检查 http://127.0.0.1:${PORT}/health ..."
ok=0
for i in $(seq 1 20); do
    if curl -fsS --max-time 3 "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
        ok=1
        break
    fi
    sleep 1
done
if [ "${ok}" = "1" ]; then
    echo "[ok] gateway healthy (systemd: $(systemctl --user is-active "${UNIT}"))"
    curl -s --max-time 3 "http://127.0.0.1:${PORT}/health"
    echo
else
    echo "[!!] health 检查失败, 请查看: journalctl --user -u ${UNIT} -n 100 --no-pager"
    exit 1
fi
