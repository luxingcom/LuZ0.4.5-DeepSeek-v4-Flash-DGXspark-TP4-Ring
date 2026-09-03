# 基准工具（scripts/benchmark）

LuZ0.4.5 基准测试工具链（脱敏版）。完整口径说明见 [FINAL-METRICS](../../docs/03-final-metrics/FINAL-METRICS-2026-09-02.md)。

## 文件清单（现行口径）

| 文件 | 用途 | 状态 |
|---|---|---|
| `bench_v2.py` | 基准主工具：流式请求 + metrics 采集 + 3 波中位统计（每请求 prefill/decode 速率） | 现行 |
| `run_bench_full_matrix.sh` | 完整矩阵 48 格（DE 18 + PR 30），FINAL-METRICS 数据来源 | **现行口径权威** |
| `run_pr400k_c2.sh` | PR400K 扩展档 C2 并发重跑（2200MHz 制） | 现行 |
| `gsm8k_full_g1r5.sh` | GSM8K 全量 1319题 双门评分（content/marker ≥0.930 门） | 现行 |
| `w9r2_gsm8k_spot.py` | GSM8K 评分器（boxed→标记→last_num 三级回退） | 现行 |
| `run_ext_400k_only.sh` | PR400K 早期扩展轮（C1 时代，03 断电中止） | 历史存档 |
| `monitor_ext_gsm8k.sh` / `server_monitor_c2_gsm8k.sh` | 长跑监控（温度/进度哨兵） | 辅助 |

## 环境要求

- Python ≥ 3.8，`requests` 库（bench_v2.py 启动时自检）
- vLLM 引擎：OpenAI 兼容端点（生产为直连 8002；8001 为 concurrency-proxy 网关示例；w9r2 默认 8003 为历史网关口径，可用 `--base` 覆盖）
- GSM8K 数据集：官方 test split（1319 题 JSONL，`--data` 指定路径，需自行下载并提供）

## 脱敏占位符替换（执行前必做）

脚本以脱敏占位符发布，替换后才能运行（真实映射见 `REDACTION-MAP.md`）：

| 占位符 | 含义 | 示例替换 |
|---|---|---|
| `_PH_NODE_IP_` | 引擎节点 IP | `127.0.0.1` 或实际节点 IP |
| `_PH_HEAD_IP_` | 管理网前三段（gid_preflight 四机数组） | `192.168.x` |
| `_PH_USER_` | ssh/路径用户名 | `ubuntu` |
| `_PH_USER_KIT_` | 工具目录 | `$HOME/w6-kit` |
| `_PH_BAKE_IMAGE_DIGEST_` | 镜像 digest 标注 | 任意标注字符串 |
| `<MGMT_OCTET>` | 管理网末段注释 | `x` |
| `<API_KEY>` | API key（w9r2 默认值） | 引擎的 key 或 dummy |

快速替换：

```bash
sed -i 's/_PH_NODE_IP_/127.0.0.1/g; s/_PH_USER_/ubuntu/g' run_bench_full_matrix.sh
```

## 最小复现路径

```bash
# 0. 冒烟（零 GPU 依赖，验证参数化与帮助信息）
python3 bench_v2.py --help
python3 bench_v2.py --dry-run --endpoint http://127.0.0.1:8002 --model deepseek-v4-flash-0731

# 1. 单格基准（每请求 prefill/decode 速率，3 波中位）
python3 bench_v2.py --endpoint http://127.0.0.1:8002 --key dummy-bench \
  --model deepseek-v4-flash-0731 --run-type pr --prefix-len 2048 --concurrency 1 --rounds 3

# 2. 完整矩阵 48 格（需先替换占位符；预计数小时）
bash run_bench_full_matrix.sh

# 3. GSM8K 全量（需自备 gsm8k_test.jsonl 1319 题）
python3 w9r2_gsm8k_spot.py --data gsm8k_test.jsonl --base http://127.0.0.1:8002 \
  --api-key dummy-bench --out gsm8k-result
bash gsm8k_full_g1r5.sh
```

## 口径速查

- `prefill_tps = prompt_tokens / TTFT`（每请求）；`decode_tps = (completion-1) / (total - TTFT)`（每请求）
- 矩阵值 = 3 波中位（uuid-prefix 冷算，前缀缓存关闭）
- 聚合口径：**总PR/总DE = 每请求吞吐 × 并发 N**（服务器每秒 token 总量），公式权威定义见 FINAL-METRICS §6

*注：`FINAL-METRICS §1` 的"±3% 内"一致性好表述适用于 PR/DE C1-C2 档；C4 及以上高并发档与个别格波间波动更大（最大 ~55%，DE_coding_C4 prefill），由 3 波中位兜底。*
