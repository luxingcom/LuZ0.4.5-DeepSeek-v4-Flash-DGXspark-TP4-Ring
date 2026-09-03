# Runbook：新节点从零拉起（LuZ0.4.5-baked）

> 目标：在 4×DGX Spark 上从零部署 LuZ0.4.5（1 head + 3 worker, TP4 环网）。所有 `_PH_*_` / `<...>` 占位符先按 REDACTION-MAP 替换。

## 0. 前置条件

- 4 台 DGX Spark（GB10/sm_121a, DPU SM121 GPU），RoCE 环网互联，SSH 互信
- 管理网 IP / 环网 netdev 就位；`node01`(head) / `node02-04`(worker)
- 已拉取镜像 `LuZ0.4.5-...-Ring-baked`（digest `_PH_BAKE_IMAGE_DIGEST_`）与模型权重

## 1. 目录布局（四机一致）

```
/opt/_PH_INSTALL_/
  models/deepseek-v4-flash-0731/     # 模型权重(ro 挂载, 不在镜像内)
  lib/libncclpin.so                  # NCCL 绑核 shim (V9) —— baked 镜像已内置, 可选宿主覆盖
  scripts/                           # 本仓库 scripts/ 部署于此
  state/                             # healthcheck rebuild 状态文件如 trailhash
/home/_PH_USER_/
  vllm-logs/ flashinfer-cache/ tilelang-cache/ b12x-cache/ vllm-cache/   # 数据挂载点
```

## 2. 安装 systemd 单元 + sudoers

```bash
# 四机: 拷贝 templates → /etc/systemd/system/ 并启用
systemctl daemon-reload
# head
systemctl enable --now vllm028-tp4-head.service vllm-healthcheck.timer concurrency-proxy.service gb10-clock-cap.service
# worker (node02-04)
systemctl enable --now vllm028-tp4-worker.service gb10-clock-cap.service
# sudoers (head, 最小权限)
cp 99-gid-preflight /etc/sudoers.d/99-gid-preflight && visudo -c
```

## 3. 启动顺序（head 先起, monitor 等 TCPStore 就绪）

1. 验证 GID：每机 `gid_preflight.sh`（预期全机 4 口 GID 非零）
2. 起 head：`bash start_tp4_head_v043.sh`（或 `systemctl start vllm028-tp4-head.service`）
3. 起 worker：`bash start_tp4_worker_v043.sh`（n 台 worker 各自执行）
4. 健康验证：`curl -sf http://127.0.0.1:8002/health` 所有机

> 依赖顺序：先挂载点/权重就位 → 起容器（baked 版无需再 pres 挂 patches/autotune，内置）→ 若使用宿主 libncclpin 覆盖才挂载。

## 4. 自愈链启停顺序（先停后操作）

```bash
# 停(顺序不可乱): 先停自愈链 timer → service → 容器 → proxy
systemctl stop vllm-healthcheck.timer
systemctl stop vllm028-tp4-head.service vllm028-tp4-worker.service   # 四机
docker rm -f $(docker ps -aq --filter name=vllm028-tp4-rank) 2>/dev/null || true
systemctl stop concurrency-proxy.service
# 操作...
# 恢复: proxy → service(timer 由 service 依赖启动) → 验证
# 验证 Loaded 24 configs + health 200
```

> ⚠️ 只停 timer 不够：Restart=always + monitor 循环会在容器删除后自动重建。必须停 service 单元。

## 5. 故障排查速查

| 症状 | 排查 | 修复 |
|---|---|---|
| 拉起即崩, 日志 `ibv_modify_qp errno 61` | `gid_preflight.sh` | `--fix` 或人工 `nmcli disconnect/connect` |
| 400 循环重启 head | TCPStore 26000 未监听 | 查 GID / NVIDIA 驱动 / 显存 |
| 满载过热 >93°C 断电 | `nvidia-smi` 温度 | `gb10-clock-cap` 降频 |
