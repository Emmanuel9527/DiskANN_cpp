# SIFT100M 三組資料布局比較

同一張 SIFT100M R64 圖、同一套 PQ 距離表，固定 query prefix、K=10、L、W、單 query thread、無 node cache。所有組別都做完整向量 exact reranking，正式量測不開 trace 或細粒度 profiling。

| 組別 | 資料布局 | 節點順序 | 搜尋 |
|---|---|---|---|
| diskann_baseline | vector 128 B + degree 4 B + neighbors 256 B；10 nodes / 4 KiB | 原始 ID | 原版 cached_beam_search |
| neighbor_only_identity | degree + neighbors，260 B；15 nodes / 4 KiB；vectors 另存，32 / page | 原始 ID，不做 clustering 重排或 block shuffling | search_split_async，GRAPH_EXPANSION=page |
| traditional_greedy | 與 baseline 相同，10 nodes / page | 既有 greedy block shuffle | 原版 cached_beam_search + --use_sector_candidates，結果映射回原始 ID |

傳統 record 不額外存 node ID，ID 由實體位置隱含。第 2 組的「clustering」依本次確認僅指 neighbor-only 密集布局，不是向量分群。

## 執行

從 repo root：

```bash
# 預設：前 1000 queries、L=20/60/120、W=16、3 次重複，每輪輪換三組順序
python3 experiments/layout_ablation/run.py

# 快速驗證（正式報告請增加 query 數和重複次數）
python3 experiments/layout_ablation/run.py --queries 100 --repeats 1

# 全部 queries、多個 beam
python3 experiments/layout_ablation/run.py --queries 10000 --repeats 3 --W 8 16 32

# 只準備、驗證、編譯
python3 experiments/layout_ablation/run.py --prepare-only
```

預設資料根目錄 `/home/emmanuel/projects/data`，可用 `--data-root` 改變。需已有 default 與 block_shuffle SIFT100M indexes，以及 `sift100m_split_shuffled/vectors.bin`（原始 ID 順序、無 header 的完整向量）。準備程式驗證向量抽樣後重用，不複製 12.8 GB vectors。

缺少 identity layout 時自動建立在 `results/layout_ablation_assets/sift100m_identity`，約新增 27.31 GB neighbor pages 與 0.4 GB identity map。正反 map 共用同一檔案。既有完整輸出會驗證並重用；不完整輸出會停止，不會自動覆寫。`layout.json` 在成功完成後才寫入。

每次執行在新的 `results/layout_ablation_<Taipei time>` 目錄留下：

- `summary.md`：可直接閱讀的比較表。
- `summary.csv`：各組各 L/W 的 recall@10、mean / p99.9 latency、inverse-mean QPS、分開的 neighbor / vector / combined reads、total reads 和 bytes。
- `manifest.json`、`commands.json`：設定、輸入路徑與實際命令。
- `verification.json`：固定 seed 的 10,000 個隨機節點，另外包含起點及邊界，核對原圖、shuffle maps、PQ codes、vectors、neighbor-only records；PQ pivots 完整比對。這是抽樣驗證，不是全資料 checksum。
- 每組 log 與結果 IDs；split 組另外有逐 query CSV。
- `*_agreement.json`：三組與 baseline 的 ordered top-10 完全相同比率。PQ tie 時 ID 重編號可能改變 tie-breaking，因此不同不一定是資料錯誤。

Recall 統一採 GT 前 10 IDs 的集合交集比例，不延伸第 10 名的距離 ties。原版結果先還原原始 ID。`inverse_mean_qps = 1e6 / mean_us` 是由搜尋延遲推算的單執行緒速率，不是整個 process 吞吐量；載入 PQ、maps、輸出檔案與準備時間不包含在 query latency。小樣本 p99.9 幾乎就是最大值，不適合推論尾延遲。

## 比較範圍

主要比較採 **整頁展開**：baseline 保留原版逐節點行為；neighbor-only 每次讀 4 KiB 後，對全部有效的 15 個 resident 及其 adjacency 做 PQ，展開全部 lists；greedy 使用原版 `--use_sector_candidates`，展開 10-node page 的所有有效 lists。三組不修改圖邊。

Neighbor-only 的 graph pages 在 query 內去重，vector 仍針對候選佇列選中的節點提交讀取，不合併 vector pages。CSV 分別列 neighbor、vector、combined-page reads、整數 total_host_reads 與平均 total reads。原版傳統布局一次讀取同時帶回 vector 與 neighbors，記入 combined，不能重複加總。原版每 query 計數透過 `DISKANN_WRITE_QUERY_STATS=1` 在搜尋計時結束後輸出，不需啟用 trace。

Greedy 的原版 sector expansion 會 exact-score 整頁節點、以 PQ 評分所有鄰居；split 會 PQ-score 頁內節點及所有鄰居，但只有選中的節點另外讀 vector 做 exact。兩者 rerank 候選策略不同，必須一併看 recall。I/O driver 也不同；本次重點是實際 host read counts，不能把全部延遲差都解釋成布局收益。

先前的逐節點對照保留為可選診斷：`python3 experiments/layout_ablation/run.py --expansion node`。主要預設已改為 `page`，不再以逐節點結果代替使用者要求的整頁搜尋。

既有 greedy index 由 repo 的 `compute_block_shuffled_order` 對圖鄰居所在 block 計票、以容量限制 greedy 放置並迭代；此 runner 重用該檔案，不重新建圖。沒有把它宣稱為已核對外部 BNF 論文的完整實作。

O_DIRECT 繞過 OS page cache，不代表清空 SSD controller cache。測試不清系統 cache、不綁核；請在裝置閒置時重複量測。讀取 bytes 是 host 請求量，不是 NAND bytes。

## 搜尋起點對齊

SIFT100M default index 的 `_disk.index_medoids.bin` / `_disk.index_centroids.bin` 含 3 個起點。只使用 disk header 的單一 medoid 會改變探索路徑，不能拿來當布局對照。

本 runner 讓 split 透過 `SEARCH_MEDOIDS`、`SEARCH_CENTROIDS` 載入相同資料，以原版 float L2 選起點。shuffled index 的既有資料沒有這些 sidecars，所以每次在結果目錄建立 `shuffled_index*` symlinks，附上經 old-to-new 映射的 3 個 medoids 與原始 centroids；不修改原始 index 檔。三組因此選擇相同 logical entry point。

## 舊逐節點診斷（非主要整頁比較）

`results/layout_ablation_20261026_031220/summary.md`：前 1,000 queries、W=16、L=20/60/120、每組一次，9 組皆完成。三個 L 的 split ordered top-10 均與 baseline 逐筆完全一致。Greedy 的 exact distance arrays 也與 baseline 完全一致，但 ID tie 排序不同；L=120 有一筆 query 的 top-10 集合在等距邊界不同，ID-based recall 為 97.59%，baseline / split 為 97.60%。診斷詳見 `tie_checks.json`。

這是單次初測，不據此判定演算法優劣。前一輪 `layout_ablation_20261026_031036` 因搜尋起點未對齊已標記 INVALID_COMPARISON，不應用來比較布局。

## 已完成的整頁 I/O 比較

`results/layout_ablation_20261026_032141/summary.md` 是整頁版本的實測：SIFT100M、前 1,000 queries、W=16、L=20/60/120、每組一次。`count_validation.json` 確認九組逐 query 的整數 I/O counts 與 summary 相符，split 每個讀回頁面的所有有效 resident 都做了 PQ。

L=120：baseline 187.050 reads/query；neighbor-only graph 175.282 + vector 177.046 = 352.328；greedy sector expansion 163.719。相對 baseline，split graph-only 降約 6.29%，但含 vector 的總 I/O 增 88.36%；greedy 總 I/O 降 12.47%。對應 recall@10 為 97.60%、97.72%、98.09%。這是固定 L 比較，並非 matched-recall 比較。
