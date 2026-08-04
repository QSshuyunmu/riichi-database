---
name: Pull Request
about: 提交代码/文档变更
title: "[PR] "
labels: ''
assignees: ''
---

## 变更内容

<!-- 简要描述 -->

## 门禁验证

<!-- 修改解析/ETL/查询代码后必须运行并粘贴结果：

python analysis/gate/run_guarded.py analysis/gate/verify_gate.py --all --data v3_200k_v2.parquet
-->

- [ ] L0 锚点通过
- [ ] L1 黄金集通过（AGARI ≥95%）
- [ ] L2 不变量 + 回归通过
- [ ] L3 统计基准通过（或 WARN 已说明原因）

## 统计口径检查

- [ ] 铳率一对一（固定目标立直家）
- [ ] 和率/放铳率局级去重
- [ ] 现物铳率 = 0（若涉及）
- [ ] 时点判定用全局事件序号

## 相关 Issue

<!-- #12 -->

## 文档

- [ ] README（中/EN/JP）已同步
- [ ] docs/ 已更新（如涉及方法论/验证）
