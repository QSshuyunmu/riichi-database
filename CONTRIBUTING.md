# 贡献指南（Contributing Guide）

欢迎贡献！本项目的核心目标是**从 HTML 牌谱构建可信事件流**——任何贡献都应服务于"数据正确性可证明"这一原则。

## 如何贡献

### 1. 报告问题（Bug / 数据疑问）

请使用 [Issue 模板](.github/ISSUE_TEMPLATE/bug_report.md) 提交，包含：
- 涉及脚本与复现步骤
- 预期结果 vs 实际结果
- **统计口径说明**（行级/局级/一对一？现物定义？）——许多"问题"其实是口径不清

### 2. 提交代码

- Fork 本仓库 → 新建分支 → 提交 PR
- **修改解析/ETL/查询代码后，必须运行门禁**：
  ```powershell
  python analysis/gate/run_guarded.py analysis/gate/verify_gate.py --all --data v3_200k_v2.parquet
  ```
  （内存护栏：长任务禁止直接 `python <script>` 裸跑）
- **统计口径硬规则**（详见 README 方法论）：
  - 铳率必须**一对一**（固定目标立直家）
  - 和率/放铳率**局级去重**（行级会因 backfill 虚高）
  - 现物铳率**必须精确为 0**——非零即 bug，不是估计
  - 时点判定用**全局事件序号**（turn 跨家不可比）
- 新增查询脚本请放入 `analysis/queries/` 并遵循现有命名与输出格式（JSON + 口径注释）

### 3. 文档

- README 三语（中/EN/JP）需同步更新
- 方法论/验证结果变更记录到 `docs/`（EVALUATION/ADR 等）

## 代码规范

- Python 3.13+，类型注解，无第三方依赖除 polars/psutil/matplotlib
- 脚本内注明数据口径（哪一层、哪一查询族）
- 禁止提交数据文件（.parquet/.db/大 JSON）

## 行为准则

保持尊重与建设性。日麻数据研究社区很小，友好交流是共同受益的前提。
