# Riichi Database — 天凤牌谱数据分析管线

> 天凤（Tenhou）四人麻将牌谱 → 数据管线 → 权威统计验证 → 读牌分析
> 数据管线全链路修复 + 门禁体系 + nodocchi 统计基准锚定

---

## 架构总览

```
天凤 XML 牌谱 (354K 局原始数据)
      │  pipeline/tenhou_to_mjai.py   转换器（赤牌 ID + 副露 m 编码权威解码）
      ▼
MJAI 事件流 (games_200k_v2, 200K 半庄)
      │  pipeline/etl_v3.py           ETL（手牌追踪 + 局级准入 ADR-005）
      ▼
v3_200k_v2.parquet (98.86M 行 / 2.05M 局)
      │  verify_gate.py               L0 锚点 → L1 黄金集 → L2 不变量+回归 → L3 统计基准
      ▼
查询族 (analysis/queries + aka) → 统计结果 (results/)
```

## 核心成果

### 1. 数据管线修复（11 个结构性 bug）

| Bug | 修复 | 验证 |
|-----|------|------|
| 转换器 m 解码错误（副露类型错乱）| 权威位布局重写 | 手牌守恒 golden test |
| 赤牌 ID 判定错误（`cp==3` vs 权威 `id%4==0`）| 赤牌 = 16/52/88 | 300 文件端到端 0 失配 |
| 副露 consumed 副本 ID 追踪错误 | 按类别移除（m 字段不编码副本）| meld 失败 31.8% → 0 |
| 国士/七对听牌漏判、dora 循环漏 N 等 | 逐一修复 | INV-2 PASS |

### 2. 数据纯净性原则（ADR-005）

- **局级准入**：kyoku 全部动作合法才入库，副本歧义局（信息论极限 ~3.8%）整局丢弃
- **现物（genbutsu）= 0 自检**：对一家立直的现物（立直家全部舍牌 + 宣言后他家舍牌）铳率**必须精确为 0**（振听规则强制）——非零即逻辑 bug，这是数据正确性的最强自检

### 3. 统计验证体系（门禁 L0-L3）

- L0 锚点测试（8 个 golden cases）
- L1 黄金样本集（200 个覆盖稀有场景的 XML，AGARI 交叉验证 ≥95%）
- L2 不变量（INV-1..10）+ 回归探针（P1-P15）
- L3 统计基准 vs **nodocchi 凤凰卓数据**（270 玩家 / 2000 万局）

### 4. 统计基准锚定（`data/baseline_stats.json`）

| 指标 | 观测 | nodocchi 基准 |
|------|------|--------------|
| 和率 | 21.1% | 21.9%（±段位差）|
| 铳率 | 12.5% | 13.1% |
| 立直率 | 18.7% | 18.2% |
| 自摸率 | 40.9% | 40.4% |
| 赤宝率 | 47.4% | 49.8% |
| 平和率 | 20.3% | 20.5% |
| 七对率 | 2.9% | 2.9% |

### 5. 读牌分析成果（`results/`）

- **现物/筋/无筋安全度梯度**：现物 0% < 筋 3.1% < 无筋 8.1%（一对一直实铳率）
- **无筋内分层**：中张 13.0% > 2·8 10.0% > 幺九 7.8% > 字牌 1.9%
- **赤牌宣言**：切赤 5 后同色端牌（1/9）听牌增多、中张减少；5x 听牌率 0%
- **押し引き**：向听 0 放铳给立直家 4.0% vs 向听 3 仅 0.8%
- **副露大类**：役牌流收支 +393 vs 食断流 -125；染手溢出听牌率 3 倍于无溢出
- 详细见 `results/RESULTS_README.md`

## 环境要求

- Python 3.13+（polars ≥1.40, psutil）
- Windows 路径硬编码于 `run_guarded.py`/`verify_gate.py` 的 `PY` 常量（按环境修改）
- 数据：天凤公开牌谱 XML（354K 局，见 [tenhou.net](https://tenhou.net)）；本仓库不含原始数据（大文件）
- 基准来源：nodocchi.moe Phoenix DB（天凤凤凰卓玩家统计）

## 目录结构

```
├── pipeline/          # 数据管线（XML→mjai→parquet + 校验）
├── analysis/          # 统计成果脚本
│   ├── queries/       # 查询族（B/V/H/L3/读牌等）
│   ├── aka/           # 赤牌专项分析
│   ├── sanity/        # 统计基准验证
│   └── gate/          # 门禁体系（L0-L3 + 内存护栏）
├── results/           # ★ 高价值统计结果（JSON）
├── data/              # 基准/黄金集（小文件）
└── docs/              # 核心文档（评估/模型/规则/ADR）
```

## 运行方式

```powershell
# 统计基准验证（nodocchi 基准门禁）
python analysis/sanity/stats_sanity.py --data v3_200k_v2.parquet --mode warning

# 门禁全链路（修改后必跑）
python analysis/gate/run_guarded.py analysis/gate/verify_gate.py --all --data v3_200k_v2.parquet

# 查询族重跑（半庄级均匀抽样）
python analysis/gate/run_guarded.py analysis/queries/b2_queries.py
```

## 数据来源与致谢

- 天凤（tenhou.net）公开牌谱数据（学术研究用途）
- nodocchi.moe Phoenix DB 统计基准
- 天凤规则权威对照：kobalab/tenhou-log（mjlog 解析）

## License

研究/教育用途。数据归天凤所有，代码 MIT。
