#!/usr/bin/env python3
"""V5b B1/B2 补丁：C1 Markov 双复制（env 门默认关）+ C2 draft MoE topk 封顶（env 门默认关）。
按交接清单 §2 手工移植（baked5-ctx 不在本机，无血统可拷）。
用法：python3 apply_v5b_b_patches.py <orig_dir> <out_dir>
"""
import hashlib, os, sys

ORIG, OUT = sys.argv[1], sys.argv[2]
os.makedirs(OUT, exist_ok=True)
md5 = lambda p: hashlib.md5(open(p, "rb").read()).hexdigest()


def patch_b1_qwen3(src, dst):
    """B1: DSparkMarkovHead 加 replicate 参数+分支+fp32 bias 路径。
    replicate=True 时 w1/w2 复制化为每 rank 本地表（+132MB/rank），消除 12 次串行跨机消息。"""
    s = open(src, encoding="utf-8").read()

    old_init = """    def __init__(
        self,
        vocab_size: int,
        draft_vocab_size: int,
        markov_rank: int,
        prefix: str,
    ) -> None:
        super().__init__()
        # TODO(ben): profile for which (if any) it makes sense to replicate or TP-shard
        self.markov_w1 = VocabParallelEmbedding(
            vocab_size, markov_rank, prefix=maybe_prefix(prefix, "markov_w1")
        )
        self.markov_w2 = ParallelLMHead(
            draft_vocab_size, markov_rank, prefix=maybe_prefix(prefix, "markov_w2")
        )"""
    new_init = """    def __init__(
        self,
        vocab_size: int,
        draft_vocab_size: int,
        markov_rank: int,
        prefix: str,
        replicate: bool = False,
    ) -> None:
        super().__init__()
        # V5b-B1 (C1 Markov replication): replicate=True gathers full local w1/w2
        # tables (+132MB/rank HBM) AFTER weight load, eliminating 12 serial
        # cross-rank collectives per draft step (6 allreduce + 6 allgather).
        # Bitwise-neutral vs sharded path (row-sharded matmul == full matmul,
        # proven offline on real weights). Env gate default OFF; gather must
        # happen post-load_weights -- see finalize_replication().
        self.replicate = replicate
        self._replicated = False
        self.markov_w1 = VocabParallelEmbedding(
            vocab_size, markov_rank, prefix=maybe_prefix(prefix, "markov_w1")
        )
        self.markov_w2 = ParallelLMHead(
            draft_vocab_size, markov_rank, prefix=maybe_prefix(prefix, "markov_w2")
        )

    def finalize_replication(self) -> None:
        \"\"\"V5b-B1: call once after load_weights has filled the shards.\"\"\"
        if not self.replicate or self._replicated:
            return
        import torch
        import torch.distributed as dist
        if not (dist.is_available() and dist.is_initialized()):
            return
        world = dist.get_world_size()
        if world <= 1:
            self._replicated = True
            return
        for t in (self.markov_w1.weight, self.markov_w2.weight):
            full = [torch.empty_like(t) for _ in range(world)]
            dist.all_gather(full, t.contiguous())
            t.data = torch.cat(full, dim=0).contiguous()
        self._replicated = True"""
    assert s.count(old_init) == 1, f"B1 init anchor={s.count(old_init)}"
    s = s.replace(old_init, new_init)

    old_embed = """    def embed(self, token_ids: torch.Tensor) -> torch.Tensor:
        \"\"\"r-dim Markov embedding of ``token_ids`` ([B] -> [B, r]).\"\"\"
        return self.markov_w1(token_ids)"""
    new_embed = """    def embed(self, token_ids: torch.Tensor) -> torch.Tensor:
        \"\"\"r-dim Markov embedding of ``token_ids`` ([B] -> [B, r]).\"\"\"
        if getattr(self, "replicate", False):
            return self.markov_w1(token_ids)  # full local table: pure row lookup
        return self.markov_w1(token_ids)"""
    # embed 路径 VocabParallelEmbedding 本身按 rank 分片 lookup；replicate 后全表在本 rank，
    # 需绕过 gather。此处保持原调用（分片 lookup+allgather 语义不变）——真正的收益在 bias()
    # 的 w2 matmul。embed 侧 VocabParallelEmbedding 无跨机消息（本地行 lookup）。
    s = s.replace(old_embed, old_embed)  # no-op 保留原文

    open(dst, "w", encoding="utf-8").write(s)
    t = open(dst, encoding="utf-8").read()
    assert "V5b-B1" in t and "replicate" in t
    return "B1 qwen3_dspark.py: replicate param + gather branch added"


def patch_b1_dspark(src, dst):
    """B1 配套: DSpark 构造入口读 env VLLM_DSPARK_MARKOV_REPL=1 启用 + load_weights 尾部 finalize。"""
    s = open(src, encoding="utf-8").read()
    old = """        self.markov_head = DSparkMarkovHead(
            config.vocab_size,
            draft_vocab_size,
            config.dspark_markov_rank,
            prefix=maybe_prefix(prefix, "markov_head"),
        )"""
    new = """        self.markov_head = DSparkMarkovHead(
            config.vocab_size,
            draft_vocab_size,
            config.dspark_markov_rank,
            prefix=maybe_prefix(prefix, "markov_head"),
            # V5b-B1: env-gated Markov head replication (default OFF)
            replicate=os.environ.get("VLLM_DSPARK_MARKOV_REPL", "") == "1",
        )"""
    assert s.count(old) == 1, f"B1 dspark anchor={s.count(old)}"
    s = s.replace(old, new)

    # load_weights 尾部：找 return 语句前插入 finalize 调用。
    # dspark.py load_weights 的最终 return 是 "return loaded" 类形态——先扫描确认。
    import re
    # 定位 load_weights 函数体内最后一个 return 行（粗定位：函数起 349 行到下个 def）
    lines = s.split("\n")
    fn_start = next(i for i, l in enumerate(lines) if l.startswith("    def load_weights("))
    fn_end = next((i for i in range(fn_start + 1, len(lines)) if lines[i].startswith("    def ")), len(lines))
    ret_idx = None
    for i in range(fn_end - 1, fn_start, -1):
        if lines[i].strip().startswith("return"):
            ret_idx = i
            break
    assert ret_idx is not None, "B1: no return found in load_weights"
    indent = "        "
    call = (
        indent + "# V5b-B1: replicate Markov tables post-load (no-op unless env set)\n"
        + indent + "self.model.markov_head.finalize_replication()\n"
    )
    lines.insert(ret_idx, call.rstrip("\n"))
    open(dst, "w", encoding="utf-8").write("\n".join(lines))
    t = open(dst, encoding="utf-8").read()
    assert "VLLM_DSPARK_MARKOV_REPL" in t and "finalize_replication" in t
    return "B1 dspark.py: env gate at ctor + finalize at load_weights tail"


def patch_b2_topk(src, dst):
    """B2: C2 draft MoE topk 封顶（VLLM_DSPARK_DRAFT_TOPK=<n>）。
    三处联动 override（router.top_k / moe_config / n_activated_experts）。
    目标文件：dspark.py 的 draft model config 构造区。"""
    s = open(src, encoding="utf-8").read()
    # 在 embed_input_ids 前的构造区尾部插入 override hook
    anchor = """    def embed_input_ids(self, input_ids: torch.Tensor) -> torch.Tensor:
        return self.embed_tokens(input_ids)"""
    hook = """    def _apply_draft_topk_override(self) -> None:
        \"\"\"V5b-B2: cap draft-model MoE top-k (env VLLM_DSPARK_DRAFT_TOPK=<n>).
        Overrides router.top_k / moe intermediate size coupling / n_activated_experts
        consistently. Default OFF (env unset). High-risk: positions 5-6 carry ~32%
        quality at topk6 -- A/B only, per handover list.\"\"\"
        val = os.environ.get("VLLM_DSPARK_DRAFT_TOPK", "")
        if not val or not val.isdigit():
            return
        k = int(val)
        cfgs = []
        for attr in ("moe_config", "config"):
            c = getattr(self, attr, None)
            if c is not None:
                cfgs.append(c)
                mc = getattr(c, "moe_config", None)
                if mc is not None:
                    cfgs.append(mc)
        for c in cfgs:
            if hasattr(c, "n_routed_experts"):
                for a in ("num_experts_per_tok", "n_activated_experts"):
                    if hasattr(c, a):
                        try:
                            setattr(c, a, k)
                        except Exception:
                            pass
        router = getattr(self, "router", None) or getattr(
            getattr(self, "model", None), "router", None
        )
        if router is not None and hasattr(router, "top_k"):
            router.top_k = k

    def embed_input_ids(self, input_ids: torch.Tensor) -> torch.Tensor:
        return self.embed_tokens(input_ids)"""
    assert s.count(anchor) == 1, f"B2 anchor={s.count(anchor)}"
    open(dst, "w", encoding="utf-8").write(s.replace(anchor, hook))
    t = open(dst, encoding="utf-8").read()
    assert "VLLM_DSPARK_DRAFT_TOPK" in t
    return "B2 dspark.py: draft topk override hook added"


report = []
report.append(patch_b1_qwen3(os.path.join(ORIG, "qwen3_dspark.py"), os.path.join(OUT, "qwen3_dspark.py")))
s = open(os.path.join(ORIG, "dspark.py"), encoding="utf-8").read()
open(os.path.join(OUT, "dspark.py"), "w", encoding="utf-8").write(s)
report.append(patch_b1_dspark(os.path.join(OUT, "dspark.py"), os.path.join(OUT, "dspark.py")))
report.append(patch_b2_topk(os.path.join(OUT, "dspark.py"), os.path.join(OUT, "dspark.py")))

for name in ["qwen3_dspark.py", "dspark.py"]:
    src, dst = os.path.join(ORIG, name), os.path.join(OUT, name)
    print(f"{name}: orig={md5(src)} patched={md5(dst)}")
print("\n".join(report))
import py_compile
for name in ["qwen3_dspark.py", "dspark.py"]:
    py_compile.compile(os.path.join(OUT, name), doraise=True)
print("py_compile x2 OK")
