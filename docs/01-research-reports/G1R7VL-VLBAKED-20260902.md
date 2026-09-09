# VL 分支同款内置交付 — `…-TP4-Ring-VL-baked`（响应 W9R14 行动项 #4）

日期：2026-09-02 ｜ 对应 ops 报告：`01-checkpoint-luz045-autotune-bak`（W9R14）

## 1. -VL 补查结论（行动项 #4 答案）

| 项 | -VL v2（6637e26f，现产）实测 | 判定 |
|---|---|---|
| autotune 文件 | `d1b3a174`（**原版未修复**）—— 当前 24 configs 命中全靠生产挂载 | ⚠️ 若直接套用 ops 去挂载的 baked 脚本会回归（hash 目录漂移），**必须同样内置** |
| 工具编码 v4 | `c8f1a3b5`（toolfix1+VL compose 版） | ✅ 已随基座内置 |
| 工具编码 v32 孪生 | `bfee7313`（toolfix1 修复版） | ✅ 已内置 |
| convertor | `a1d07133`（v2 两参修复版） | ✅ 已内置 |

## 2. 内置交付物

**镜像**：`REGISTRY_HOST:5000/vllm/vllm-openai:LuZ0.4.5-DeepSeek-v4-Flash-DGXspark-TP4-Ring-VL-baked`
- registry index digest `sha256:<INDEX_DIGEST>…` ／ arm64 config `sha256:<CONFIG_DIGEST>…`（index-vs-config 会计差异同 W9R14/W1 附录 A，**同一内容**）
- FROM `-VL` v2；构建 = Dockerfile 纪律（非 commit）：基座预断言 d1b3a174 → cp 原版 `.bak-orig-20260902`（沿用 ops 镜像惯例）→ COPY 修复版（源 = `/opt/_PH_INSTALL_/patches/`，md5 `702f8f56`）
- 烘焙验证门全过（`BAKE-VERIFY-ALL-PASS`）：baked md5 + 原版备份 md5 + VL 三件资产 spot 断言 + py_compile + **SET-ENV 行为验证**（`RESOLVE=> /tmp/at-vl-baked-test/autotune_configs.json` 固定路径，无 hash 子目录）；fallback 分支由 md5 与 ops `-baked` 同文件等价保证
- 四机已预拉：node02/node03/node04 config `<CONFIG_DIGEST>` 一致；node01 为构建机显示 index digest，**内容级证明** = node01/node03 各自起容器实测同文件 md5 `702f8f56` ✓

**脚本配套变体**（切换时 cp 覆盖主名，同 ops `*.baked-20260902` 用法；命名加 `vl-` 前缀防与检查点配套混淆）：
- `start_tp4_head_v043.sh.vl-baked-20260902`（仅 node01）md5 `cd42a07d`：R5→-VL-baked + 删 L57 挂载行
- `start_tp4_worker_v043.sh.vl-baked-20260902`（四机一致）md5 `8e19e631`：R5→-VL-baked + 删 L38 挂载行
- 变体 bash -n 通过；挂载残留 grep=0

**顺带修正**：node01 worker 主脚本 R5 此前漏更仍指 Ring（其余三机均已 -VL，运行容器四机实为 -VL 无恙）——已修为 -VL（bak：`.bak-r5fix-20260902`），四机主脚本恢复一致。

## 3. 切换路径（ops 执行）

1. 停自愈链 → 停容器
2. node01：head 变体 cp 覆盖主名；node02/node03/node04（及 node01）：worker 变体 cp 覆盖主名
3. bash -n + 四机 md5（8e19e631 / head cd42a07d）
4. `w9r4_restart_guard.sh` 重启 → 验证 `Loaded 24 configs` + health=200 + 工具编码请求 200
5. 回退：R5 回 `-VL`（保留挂载）guard 重启

**并窗建议**：本切换功能上为 no-op（挂载版与内置版同 md5），可单独占窗，也可与 W2 视觉切换（挂载 dsv4-vision-exp / k=3 / max-model-len 65536 / limit-mm 4 图 / served-model-name）**并窗执行**省一次生产重启；并窗时 W2 功能门（boot 哨兵/合成图/span 原子性/OCRBench/TTFT）由测试侧重跑兜底。默认建议：若追求单变量则先 baked 后 W2 两窗。

---
*证据：构建日志 BAKE-VERIFY-ALL-PASS；`docker run --entrypoint md5sum` 双机实测；四机 `docker image inspect` + `docker ps`；脚本 md5 表见上。*
