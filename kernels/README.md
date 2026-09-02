# kernels/ — Kernel 资产

本目录归档 LuZ0.4.5 检查点版本相关的 kernel 工作产物（源码 / 分析 / 交付物）。

## 当前状态

| 项 | 状态 | 说明 |
|---|---|---|
| 现役计算路径 | B12X（flashinfer）+ W4A4 | 生产 MoE 路径，配置见 `../scripts/w6_env.txt` |
| routeA / routeB | No-Go（归档） | 判定见 `../docs/05-kernels-patches/README.md` |
| routeB FP8 kernel 改进 | 立项（开发中） | P0 NCU 微基准 → P1 SMEM/流水重构 + A-quant 融合，后续版本交付 |
| NVFP4 双 kernel | 规划 | kernel1（routeA→routeB MoE GEMM）+ kernel2（v17 sparse MLP） |

## 组织方式（参照 LuZ0.3.1）

按主题 + 日期子目录归档：

```
kernels/
  <kernel-主题>-<阶段>-<YYYY-MM-DD>/
    README.md          # 说明
    <源码/补丁/数据>
```

> 当前检查点版本以生产固化为主，kernel 深度资产随后续开发轮次归档。
