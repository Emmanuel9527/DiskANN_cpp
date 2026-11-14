# A/B/C/D40/D100/E-host 實驗

本組腳本用同一張 SIFT100M R64 graph、PQ codes、原始 10,000 query prefix、3 個 logical medoids、K=10、單 query thread、無 node cache。Clustering 指既有 greedy BNF block shuffle。跑之前由使用者執行編譯；wrapper 內會呼叫 cmake build。

| Case | Layout / expansion | Full-vector policy |
|---|---|---|
| A | 原始 full+nbr，10 nodes/page，原版逐節點展開 | 原版隨頁讀回 vectors 並精算 |
| B | full+nbr，BNF capacity=10，原版 sector expansion | 精算整頁 resident vectors |
| C | nbr/full 分離，原始 ID 順序，15-node graph page 整頁展開 | traversal 後讀全部待精算候選 |
| D100 | nbr/full 分離，nbr BNF capacity=15，整頁展開 | traversal 後讀全部待精算候選 |
| D40 | 同 D100 | traversal 後，按 PQ 排名取前 40%，至少 K 個 |
| E_host | 同 D100 的 graph traversal | 不執行 SSD 端功能；只量已實作的 host traversal，剩餘成本 X 未知 |

C 與 D100 使用同一個 deferred driver，因此只改 nbr 的排列；D100 與 D40 只改精算比例。它們與舊 `SEARCH_MODE=baseline` 的逐 beam vector I/O 時程不同，不把舊結果混入新表。A 的搜尋策略是原版逐節點；B/C/D/E 利用整頁，是完整方案比較，不是純 layout 控制實驗。

待精算候選 N = 整段 traversal 期間被 beam 選中的節點，先去重，再按 PQ distance / logical ID 排序。不是所有發現的鄰居，也不是最終 queue 的 L 個節點。D40 讀 `min(N, max(K, ceil(0.4*N)))` 個 vectors。所有 split cases 的 vector pages 都不合併重複請求。向量檔維持原始 logical ID 順序。Full-vector exact scores 不影響 traversal。

E_host 的 `query_mean_ms`、`query_p95_ms`、recall 留空，避免當作完整搜尋結果。另報 `host_traversal_mean_ms` / p95。若採 serial 或「未被 host traversal 遮蔽的剩餘成本」模型，可寫 `T_E(q) = T_host(q) + X(q)`，X 包含未量到的 SSD vector reads、exact、提交/回傳成本；不能從本測試推算 X，也不能把 host p95 與未知 X 的 p95 直接相加。E 的 host block mean latency 只包含 neighbor requests，SSD 內部 latency 未知，不把 X 加進 request-weighted host block mean。

## 執行

在 repo root：

```bash
# 小樣本檢查：會編譯，跑六個 cases，各 100 queries，檢查 D/E 計數一致性
bash experiments/abcd/run.sh --out results/abcd_smoke --queries 100 --repeats 1 --L 60 --W 8

# 主要 query latency / recall / IO counts：108 組，輪換順序
bash experiments/abcd/run.sh --out results/abcd_perf --queries 10000 --repeats 3 --L 60 120 --W 8 16 32

# 獨立 block tracing：36 組，使用者需 sudo 權限
bash experiments/abcd/run.sh --out results/abcd_block --trace-block --queries 10000 --repeats 1 --L 60 120 --W 8 16 32

# Trace 完成後做分析
python3 experiments/abcd/analyze_block.py results/abcd_block
```

`--out` 必須是新目錄，已有輸出不會覆寫。可用 `--cases A B C D100 D40 E_host` 選組別；使用部分 cases 時，D/E 計數檢查只涵蓋實際執行的組別。D40 的 40% 可能降低 recall；主 sweep 固定 L/W，若要 matched-recall 需依輸出調整 L 再跑。

沿用現有 `results/layout_ablation_assets/sift100m_identity` 與 `/home/emmanuel/projects/data/sift100m_split_shuffled`。缺 identity 時由 prepare.py 建立；不重新建圖或 BNF。各 job 使用明確環境變數，B 的 medoid sidecars 映射為 shuffled IDs。`manifest.json`、`jobs.json`、`commands.json` 保留來源、環境、程式 SHA256 與命令。

## 結果

- `query_summary.csv`：case / L / W / repeat、各類平均 host reads、bytes、recall、query mean / p95。E 只填 host traversal 與未知 X。
- `consistency.json`：D100/D40/E_host 的 graph 工作量計數是否一致，D40 是否依候選池選取正確比例。計數一致不等於完整 traversal 序列驗證。
- tracing 另外保存每 job `block.dat` / `block.txt`、filefrag 前後 extent、mount/device metadata；native 記 access.csv，split 記 queries.csv.io.csv。
- 分析後 `block_summary.csv`：`kind=neighbor/vector/combined/all`；`all` 是成功配對 requests 的數量加權 mean，不是把 neighbor mean 和 vector mean 相加。
- `block_audit.json`：配對排除原因、LOST、extent、同 sector 重疊等資訊。無有效樣本、LOST 或非空 report.log 的 job 不產生有效 block latency。

解析使用同一套規則處理 native 與 split：檔案 offset 轉 parent-device sector；先核對 host 計數；只接受搜尋程序對預期 sector 發出的 4 KiB request 唯一 issue/complete 配對。某 sector 的 issue 次數與 host 次數不符時整個 sector 排除。未配對樣本不設為零，須同時查看 matched_pct。這是 aggregate 配對，沒有聲稱逐 query block 時間窗配對。只支援記錄中能解析的普通磁碟/分割區，不臆測 device-mapper 對應。

Block mean 不含 issue 前排隊，也不等於 NAND latency。Perf 與 block trace 分開執行；trace run 的 query latency 有 instrumentation 開銷，主要 query latency 請採 perf run。

本次提供程式與執行指令；尚未代使用者編譯或執行新 deferred 模式。請先跑 smoke，成功後再跑正式 sweep。
