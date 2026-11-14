# SIFT100M trace-driven MQSim oracle 實驗

已完成的報告：[REPORT.md](../../results/mqsim_trace_oracle_20261109/REPORT.md)。完整假設、數據與限制以報告為準。

本實驗使用既有 SIFT100M `results/abcd_block/r1_E_host_L*_W*` 紀錄：split BNF / page expansion / traverse_only；不是 vanilla DiskANN，也未新增完整 CSD traversal。每組最前 1,000 queries，完整 block/request 配對者才納入。

## 重跑

在 repo 根目錄，選擇新的輸出路徑：

```bash
python3 experiments/mqsim_trace_oracle/prepare.py --out results/mqsim_trace_oracle_repeat --queries 1000
python3 experiments/mqsim_trace_oracle/build.py results/mqsim_trace_oracle_repeat
python3 experiments/mqsim_trace_oracle/run_replay.py results/mqsim_trace_oracle_repeat
python3 experiments/mqsim_trace_oracle/analyze.py results/mqsim_trace_oracle_repeat
python3 experiments/mqsim_trace_oracle/plot.py results/mqsim_trace_oracle_repeat
python3 experiments/mqsim_trace_oracle/report.py results/mqsim_trace_oracle_repeat
```

需求：g++、Python、numpy；analyze.py 另需 pandas，plot.py 另需 matplotlib 及 Noto CJK font。build.py 使用先前 pipeline_lab 的 logging-only MQSim source，複製後建置，不修改安裝。可用 `--backend /path/to/instrumented/src` 指定其他副本。不要指向未加入 lab_trace calls 的原始 source。

這次為節省編譯時間，直接連結先前 pipeline_lab 的 backend objects，只重新編譯 replay.cpp；manifest.json 記錄每個 object SHA256 與原 backend manifest。`provenance.json` 記錄輸入及原始碼 hashes。結果目錄保存本次 script/source 副本。

本機預設 Python 沒有 pandas；本次未安裝新套件，使用已存在的 CPython 3.11 和 uv cached wheels 做數據分析：

```bash
/home/emmanuel/.local/share/uv/python/cpython-3.11.18-linux-x86_64-gnu/bin/python3 experiments/mqsim_trace_oracle/analyze_local.py results/mqsim_trace_oracle_20261109
```

這是本機離線 fallback；一般具備 pandas/numpy 的 Python 直接執行 analyze.py 即可。

## 政策

- Baseline：每筆 request 在正式 demand 到達時送進 TSU。
- Oracle：上一批全部完成 + 1 ns 時開始預讀下一批；保持 trace 的批內 issue offsets。下一批正式 demand 仍按模擬上一批完成 + 實測 host gap 到達。若完成／正在讀則沿用，不重複派發。
- Batch barrier：全部正式 demand 已到達，且該批所有 NAND reads 完成，才進下一批。
- 每筆 request 仍執行一次 NAND read；沒有跨批永久 cache。空間足夠，但不把無限 cache 節省重複讀的效果混入。
- 初始 batch 無預讀，query 之間互不推測；只 ahead 一批，不是任意多輪 oracle。
- 假設知道所有下一批地址，沒有 PQ／候選發現／VUC 成本。保持 trace 搜尋路徑，不計 full-vector rerank。

## 模型與時間

8 channels × 4 chips × 2 dies × 1 plane，4 KiB read，50/100 μs array，0.290 μs command，12.288 μs data-out。TSU_OutOfOrder 的 read 路徑同 chip 串行；原始程式不變。

實體地址資源分配有 stripe(LBA/8) 與 splitmix64 兩種；都不是商用 SSD 真實 FTL。每 die 內的 page 一對一緊湊映射以避免巨量不用的模擬記憶體，不改 channel/chip/die 分布，不產生別名。

trace 配對是 block_rq_complete → 下一批 block_rq_issue；微秒精度，並非 hardware completion/doorbell。Gap 含 host 搜尋工作與 I/O stack。原始 trace 的 background I/O 不進模擬，因此 baseline 空窗可用資源結論限孤立單 query 模型。

## 驗證

分析會 assert：36 組全部 request 完成、固定階段時長、channel 無重疊、die array 無重疊、chip 串行、兩策略相同地址序列與 gap、每 query oracle 不慢於 baseline、baseline host gap 無 channel/array 工作。詳見 validation.json。
