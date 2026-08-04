# Riichi Database — Tenhou Paifu Data Analysis Pipeline

> Tenhou 4-player mahjong paifu (game logs) → data pipeline → authoritative statistical validation → reading analysis
> Full pipeline repair + validation gate system + nodocchi statistical baseline anchoring

---

## Architecture

```
Tenhou XML paifu (354K games raw)
      │  pipeline/tenhou_to_mjai.py   Converter (aka ID + meld m-bit authoritative decode)
      ▼
MJAI event stream (games_200k_v2, 200K hanchan)
      │  pipeline/etl_v3.py           ETL (hand tracking + kyoku-level admission ADR-005)
      ▼
v3_200k_v2.parquet (98.86M rows / 2.05M kyoku)
      │  verify_gate.py               L0 anchor → L1 golden set → L2 invariants+regression → L3 stats baseline
      ▼
Query families (analysis/queries + aka) → Results (results/)
```

## Key Results

### 1. Pipeline Repair (11 structural bugs)

| Bug | Fix | Validation |
|-----|-----|-----------|
| Converter m-decode error (meld types scrambled) | Authoritative bit layout rewrite | Hand-conservation golden test |
| Red-five ID error (`cp==3` vs authoritative `id%4==0`) | Aka = IDs 16/52/88 | 0 mismatch across 300 files end-to-end |
| Meld consumed copy-ID tracking error | Category-based removal (m field encodes no copy) | Meld-fail 31.8% → 0 |
| Kokushi/chiitoi wait misses, dora-loop off-by-one, etc. | Fixed individually | INV-2 PASS |

### 2. Data Purity Principle (ADR-005)

- **Kyoku-level admission**: a kyoku enters the DB only if all actions validate; copy-ambiguity kyoku (info-theoretic ~3.8%) are dropped wholesale
- **Genbutsu (safe tile) = 0 self-check**: a genbutsu tile (all riichi-player discards + post-riichi discards by others) **must have exactly 0 deal-in rate** (furiten rule) — non-zero means a logic bug, not estimate error. This is the strongest correctness self-check.

### 3. Validation Gate (L0-L3)

- L0 anchor tests (8 golden cases)
- L1 golden sample set (200 XML covering rare scenarios, AGARI cross-validation ≥95%)
- L2 invariants (INV-1..10) + regression probes (P1-P15)
- L3 stats baseline vs **nodocchi Phoenix DB** (270 players / 20M games)

### 4. Statistical Baseline Anchoring (`data/baseline_stats.json`)

| Metric | Observed | nodocchi baseline |
|--------|----------|-------------------|
| Win rate | 21.1% | 21.9% (±dan gap) |
| Deal-in rate | 12.5% | 13.1% |
| Riichi rate | 18.7% | 18.2% |
| Tsumo share | 40.9% | 40.4% |
| Red-dora share | 47.4% | 49.8% |
| Pinfu share | 20.3% | 20.5% |
| Chiitoi share | 2.9% | 2.9% |

### 5. Reading-Analysis Results (`results/`)

- **Genbutsu/suji/non-suji safety gradient**: genbutsu 0% < suji 3.1% < non-suji 8.1% (one-to-one true deal-in rates)
- **Non-suji stratification**: middle 13.0% > 2·8 10.0% > terminals 7.8% > honors 1.9%
- **Red-five declaration**: after discarding red 5, same-suit terminals (1/9) waits increase, middles decrease; 5x wait rate 0%
- **Oshi/hiki**: at tenpai deal-in-to-riichi 4.0% vs 0.8% at 3-shanten
- **Meld classes**: yakuhai-flow +393 vs tanyao-flow -125 pts; dye-overflow tenpai rate 3× non-overflow
- Details: `results/RESULTS_README.md`

## Requirements

- Python 3.13+ (polars ≥1.40, psutil)
- Windows-specific Python path hardcoded in `run_guarded.py`/`verify_gate.py` `PY` constant (adjust per environment)
- Data: public Tenhou XML paifu (354K games, see [tenhou.net](https://tenhou.net)); this repo excludes raw data (large files)
- Baseline source: nodocchi.moe Phoenix DB (Tenhou phoenix-room player statistics)

## Layout

```
├── pipeline/          # Data pipeline (XML→mjai→parquet + validation)
├── analysis/          # Analysis scripts
│   ├── queries/       # Query families (B/V/H/L3/reading, etc.)
│   ├── aka/           # Red-five focused analysis
│   ├── sanity/        # Stats baseline validation
│   └── gate/          # Validation gate (L0-L3 + memory guard)
├── results/           # ★ High-value statistical results (JSON)
├── data/              # Baseline / golden set (small files)
└── docs/              # Core docs (evaluation/model/rules/ADR)
```

## Usage

```powershell
# Stats baseline validation (nodocchi-anchored gate)
python analysis/sanity/stats_sanity.py --data v3_200k_v2.parquet --mode warning

# Full validation gate (run after any change)
python analysis/gate/run_guarded.py analysis/gate/verify_gate.py --all --data v3_200k_v2.parquet

# Re-run a query family (hanchan-level uniform sampling)
python analysis/gate/run_guarded.py analysis/queries/b2_queries.py
```

## Data Sources & Credits

- Tenhou (tenhou.net) public paifu data (academic research use)
- nodocchi.moe Phoenix DB statistical baseline
- Authoritative mjlog reference: kobalab/tenhou-log

## License

Research/education purposes. Data belongs to Tenhou; code MIT.
