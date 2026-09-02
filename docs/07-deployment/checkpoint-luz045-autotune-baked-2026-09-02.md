# LuZ0.4.5 检查点准备：autotune 补丁内置镜像 + 相关文件重写

**日期**：2026-09-02
**工作流**：部署前检查 / 检查点版本准备（W9R14）
**参与成员**：主理人（工程督导）执行；SRE 运维纪律

---

## 📌 TL;DR（执行摘要）

- **任务**：将 autotune 补丁从"挂载 patches 覆盖"改为"内置到检查点镜像"，消除开源推送对主机私有 patches 文件的依赖。
- **复查结论**：生产挂载版补丁（702f8f56）逻辑正确——`VLLM_FLASHINFER_AUTOTUNE_CACHE_DIR` 设置时跳过 hash 子目录、固定路径写 `autotune_configs.json`；未设置时完全回退原版（向后兼容）。镜像内置原版（d1b3a174）未带此修复。
- **内置完成**：新检查点镜像 `LuZ0.4.5-DeepSeek-v4-Flash-DGXspark-TP4-Ring-baked`（digest sha256:153e31d2）已 push registry；内置后 md5=702f8f56、py_compile OK、行为验证固定路径命中、W9R10 标记在位。
- **相关文件重写**：head/worker start 脚本移除 autotune patches 挂载行（内置后挂载会覆盖镜像内修复版）；w6_env 的 `VLLM_FLASHINFER_AUTOTUNE_CACHE_DIR`（补丁触发开关）与 `VLLM_MOE_DYNAMIC_TILE_CAP=0` 保留。
- **生产切换**：生产 `-VL` 由修复团队处理中，未动生产主脚本；检查点配套脚本 `*.baked-20260902` 已四机就位，切换时用。

---

## 🎯 核心结论卡片

| 项目 | 内容 |
|------|------|
| 整体评级 | 🟢 通过（检查点版本已就绪） |
| 新检查点镜像 | `LuZ0.4.5-DeepSeek-v4-Flash-DGXspark-TP4-Ring-baked`（digest sha256:153e31d27b08…df18b72） |
| autotune 内置后 md5 | 702f8f561496948bb0ac3d075d12670e（=生产挂载版） |
| 原版备份 | 容器内 `.bak-orig-20260902`（镜像层内保留） |
| 阻塞项 | 0（生产切换待督导/修复团队确认） |
| 严重度 | 🔴0 / 🟠0 / 🟡1（生产主脚本未切换）/ 🟢0 |

---

## 1. 复查：autotune 补丁参数（W9R14）

### 1.1 补丁机制回顾（G1r6 时代遗留）

- **问题根因**：`resolve_flashinfer_autotune_file` 原版按 `root / hash(runner)` 写缓存，`aot_compile_hash_factors` 跨重启漂移 → 缓存目录 hash 变化 → 每次全量重新 autotune（日志 `24 new, 0 from previous`），跨重启性能 ±2-4% 噪声。
- **修复版**（生产挂载，md5=702f8f56）：设置 `VLLM_FLASHINFER_AUTOTUNE_CACHE_DIR` 时跳过 hash 子目录，固定写 `<dir>/autotune_configs.json`，跨重启稳定命中（`Loaded 24 configs`）。
- **实现方式（被替换）**：`<INSTALL_DIR>/patches/flashinfer_autotune_cache.py` 通过 start 脚本 `-v ...:ro` 挂载覆盖镜像内文件——**主机私有文件，无法随镜像分发 → 开源推送/克隆部署会失效**。

### 1.2 复查结论（参数核对）

| 项 | 值 | 判定 |
|---|---|---|
| 触发开关 env | `VLLM_FLASHINFER_AUTOTUNE_CACHE_DIR`（vllm.envs 读取） | ✅ 运行时参数，保留 |
| 生产 env 值 | `/root/.cache/vllm/autotune-g1r6` | ✅ 保留（缓存可复用） |
| 固定路径产出 | `<dir>/autotune_configs.json` | ✅ 行为验证命中 |
| fallback 分支 | 未设置 env → 原版 hash 路径逻辑 | ✅ 向后兼容 |
| 镜像内原版位置 | `/usr/local/lib/python3.12/dist-packages/vllm/model_executor/warmup/flashinfer_autotune_cache.py` | ✅ 与挂载目标一致 |
| 镜像内原版 md5 | d1b3a174（未修复） | ⚠️ 需内置修复版 |
| 其他函数 | `flashinfer_autotune_cache_hash` / `write_flashinfer_autotune_cache` 两版一致 | ✅ 无差异 |

### 1.3 代码差异（修复版 vs 镜像原版）

```diff
 def resolve_flashinfer_autotune_file(runner):
     override_dir = envs.VLLM_FLASHINFER_AUTOTUNE_CACHE_DIR
     if override_dir:
+        # W9R10 手动定义模式: 固定路径跨重启命中
         root = Path(override_dir).expanduser()
+        output_dir = root
+        output_dir.mkdir(parents=True, exist_ok=True)
+        return output_dir / "autotune_configs.json"
     else:
         from flashinfer.jit import env as flashinfer_jit_env
         ...
     output_dir = root / flashinfer_autotune_cache_hash(runner)
```

仅 `override_dir` 分支处理不同（修复版 early return）；其余逻辑逐字节一致。

---

## 2. 内置过程与证据链

### 2.1 执行步骤（<MGMT_OCTET> = registry 主机）

1. 拉取生产修复版（702f8f56）与镜像原版（d1b3a174）diff 确认差异范围
2. 基于 `LuZ0.4.5-DeepSeek-v4-Flash-DGXspark-TP4-Ring` 创建容器（`--entrypoint sleep`，规避默认 vLLM CLI entrypoint）
3. 覆盖镜像内文件 + 备份原版 `.bak-orig-20260902` + `chmod 644`
4. 验证：md5 / py_compile / import / W9R10 标记 / 行为级验证
5. `docker commit` → tag `-baked` → `docker push`

### 2.2 验证证据

| 验证项 | 结果 |
|---|---|
| 覆盖后 md5 | `702f8f561496948bb0ac3d075d12670e` ✅（=生产挂载版） |
| py_compile | OK ✅ |
| import 验证 | `resolve_flashinfer_autotune_file` / `write_flashinfer_autotune_cache` 可调用 ✅ |
| 行为验证（设 env） | `SET-ENV => /tmp/autotune-test/autotune_configs.json`（无 hash 子目录）✅ |
| 行为验证（未设 env） | `override_dir=None`（fallback 原版保留）✅ |
| W9R10 标记 | count=1 ✅ |
| registry 重拉验证 | md5=702f8f56 + marker=1 ✅ |
| push digest | `<BAKE_IMAGE_DIGEST>` |

### 2.3 registry tags 现状

```
LuZ-0.4.5-UP28                      （修复团队其他变体）
LuZ0.4.5-DeepSeek-v4-Flash-DGXspark-TP4-Ring       （修复团队检查点基线，保留）
LuZ0.4.5-DeepSeek-v4-Flash-DGXspark-TP4-Ring-VL     （修复团队生产部署目标）
LuZ0.4.5-DeepSeek-v4-Flash-DGXspark-TP4-Ring-baked  （本次新增：autotune 已内置）★
```

---

## 3. 相关文件重写清单

| 文件 | 变更 | 状态 |
|---|---|---|
| `start_tp4_head_v043.sh` | 移除 patches 挂载行（原 L57） | ✅ 检查点配套版 `start_tp4_head_v043.sh.baked-20260902` 已同步 <MGMT_OCTET> |
| `start_tp4_worker_v043.sh` | 移除 patches 挂载行（原 L38） | ✅ 检查点配套版四机一致（md5 d904b17c） |
| `w6_env.txt` | **不改**：`VLLM_FLASHINFER_AUTOTUNE_CACHE_DIR`（补丁触发开关）+ `VLLM_MOE_DYNAMIC_TILE_CAP=0` 保留 | ✅ |
| 镜像内补丁文件 | 原版 d1b3a174 → 修复版 702f8f56（内置） | ✅ 已 commit + push |

**要点**：内置后 start 脚本**必须**移除挂载行——否则挂载（`ro`）优先级高于镜像内文件，会覆盖内置修复版，等于白内置。

---

## 4. 生产切换交接（待督导/修复团队确认）

- **当前状态**：生产 `-VL` 部署由修复团队处理中；四机生产主脚本仍含 patches 挂载（未动）。
- **注意**：`-VL` 镜像未内置 autotune 修复 → 若生产最终切 `-VL`，需保留挂载或同样内置（待修复团队确认 `-VL` 内容）。
- **切换路径（切 `-baked` 时）**：
  1. 停自愈链（timer → service）→ 停容器
  2. 四机 `cp start_tp4_*_v043.sh.baked-20260902 start_tp4_*_v043.sh`（head 仅 <MGMT_OCTET>）
  3. `bash -n` + 四机 md5 一致校验
  4. 恢复容器/service/timer → 验证 `Loaded 24 configs` + 预热段 `[warmup] http=200`
- **开源发布影响**：发布副本 `release/luz045-github/scripts/` 已用检查点配套脚本（脱敏后，无挂载、R5=`-baked`），与镜像自洽，可随镜像分发。

---

## ✅ 行动清单（按优先级排序）

| # | 行动 | 负责 | 紧急度 | 预期完成 |
|---|------|------|--------|---------|
| 1 | 修复团队确认 `-VL` 与 `-baked` 的最终生产选型；若选 `-baked` 则四机切配套脚本并移除挂载 | 督导/修复团队 | P0 | 生产恢复时 |
| 2 | 生产切换后验证：`Loaded 24 configs` 命中 + 预热段 http=200 + 工具编码请求正常 | SRE | P0 | 切换后 |
| 3 | 完整 benchmark 流程（督导通知后）产出内置性能基准，填充 release `03-final-metrics/` + `data/` | 督导编排 | P1 | 生产稳定后 |
| 4 | `-VL` 镜像补查：确认其 autotune/工具编码状态，决定是否同样 baked | 修复团队 | P1 | 本次窗口 |

---

## ⚠️ 待完善 / 已知局限

- **`-VL` 镜像内容未知**：修复团队正在部署的 `-VL`（96a6d40b，35.7GB）未在本报告覆盖范围内核验 autotune 内置情况；若生产最终用 `-VL`，需单独确认其补丁状态。
- **镜像不一致隐患（此前发现，未在本轮解决）**：<MGMT_OCTET> 本地 `Ring`(无-VL)=daf0b7af(35.6GB) vs <MGMT_OCTET> 本地同 tag=98032338(22.5GB)——同一 tag 两机不同镜像，权威 digest 已对齐到 <MGMT_OCTET>/registry（本报告基于 <MGMT_OCTET> 的 98032338 验证）。四机切换前需统一 `docker pull` 到同一 digest。
- **缓存放复用**：`autotune-g1r6` 缓存路径在 `-baked` 上复用（基座相同应兼容）；若首次启动 `0 from previous` 属正常冷启动，非回归。

---

## 📚 数据来源 & 证据索引

- 生产挂载版补丁：`node0X:<INSTALL_DIR>/patches/flashinfer_autotune_cache.py`（md5 702f8f56）
- 镜像内置原版：`LuZ0.4.5-...-Ring` 容器内 `vllm/model_executor/warmup/flashinfer_autotune_cache.py`（md5 d1b3a174）
- 内置脚本/验证脚本：本地 `.window-tmp/autotune-builtin/bake_autotune_inner.sh` / `verify_baked_autotune.py`
- 检查点配套脚本：四机 `/home/<USER>/w6-kit/start_tp4_*_v043.sh.baked-20260902`（worker md5 d904b17c / head md5 0f6161fc）

---

> 本报告由工程保障团队 AI 协作生成，关键决策请由人类工程负责人复核。
