# MQSim read pipeline 實作練習

已執行的結果：[results/mqsim_pipeline_lab](../../results/mqsim_pipeline_lab)。所有圖都來自實際 MQSim backend event 的模擬時間，不是手繪的預期結果。

原始碼來源：`/home/emmanuel/projects/MQSim`，commit `51f0f2d3fed92d88ef4a0fa61a38024b07bf9d16`，執行時工作樹乾淨。沒有修改原安裝；instrumentation 與建置全部位於結果目錄的副本。這次明確選用 `TSU_OutOfOrder`，不代表其他 TSU policies、你的 nvmevirt daemon 或商用 SSD 必然相同。nvmevirt 版本的 TSU_Base/TSU_OutofOrder 可見額外統計碼，並非此次執行來源。

## 重跑

從 DiskANN_cpp 根目錄執行（輸出必須是新目錄）：

```bash
python3 experiments/mqsim_pipeline_lab/run.py --out results/mqsim_pipeline_lab_repeat
```

可用 `--mqsim /path/to/MQSim` 指定來源；patch 錨點及數值驗證針對本次版本，不保證任意 fork 相容。需要 g++、Python 3、matplotlib。編譯使用最多 4 個 compiler processes；這不是完整 SSD workload simulator 的命令列，而是連結原生 TSU、PHY、NAND、event engine 的小型 driver。

重新分析現有 trace：

```bash
python3 experiments/mqsim_pipeline_lab/analyze.py results/mqsim_pipeline_lab
```

## 實驗範圍與設定

固定 2 channels × 2 chips/channel × 2 dies/chip × 1 plane/die；每 plane 4 blocks、每 block 64 pages。Read-only、SLC、每筆資料 4096 bytes。所有 array reads 設為 50 us，額外 Ready/Busy signal delay 明確設為零。NVDDR2 channel width=1 byte、TwoUnitDataOutTime=6 ns，其餘 ONFI timing 使用原 constructor 預設值。

- Command/address：`t_CS + 6*t_WC + t_WB + t_RR = 290 ns`。
- Array execution：50,000 ns。
- Data-out：`4096 / 1 / 2 * 6 = 12,288 ns`。
- 無競爭單筆總計：62,578 ns = 62.578 us。

Data-out 是 NAND→controller，不是 PCIe→host。這是教學參數，沒有校準成主機上的真實 SSD。

Driver 直接提供實體地址，在 TSU 入口注入 `USERIO` read transactions；FTL 物件僅提供 scheduler 所需的非緊急 GC predicate，GC 不註冊事件。不走 NVMe、PCIe、L2P、DRAM data cache、ECC/read-retry；不模擬距離計算或真實 traversal。頁面不經寫入 preconditioning，這些 reads 僅用來測試地址、排程與時序，不驗證資料內容。沒有背景讀寫。

`dispatch` = PHY 接受 command；`cmd_start` = channel 真正開始傳 command，兩者在 PHY interleaving 對照中可能不同。不要把 dispatch 直接當成 bus service start。

## 結果

| 情境 | 兩筆都完成的時間 | 觀察 |
|---|---:|---|
| 不同 channels | 62.578 us | Command、array、data-out 均能跨 channel 重疊 |
| 同 channel、不同 chips | 74.866 us | Array 重疊、data-out 串行 |
| 同 channel/chip、不同 dies，原 TSU | 125.156 us | 此 scheduler 路徑沒有使用 die interleaving |
| 同 die/plane、不同 pages | 125.156 us | 第二筆等第一筆 data-out 完成 |
| 同 chip 不同 dies，直接送 PHY 的對照 | 74.866 us | PHY 能執行 die interleaving，但繞過 TSU，不能當原 scheduler 結果 |

![Read cases](../../results/mqsim_pipeline_lab/read_cases.png)

每張圖另有 SVG 與 PDF。黃色是 TSU 之前/之中的等待（submit→dispatch），紫色是 array 已完成但 data-out 尚未開始；黑色 command 只有 0.290 us，因此按真實比例顯示很細。

## 追 scheduler：照這條路徑讀

以下連結指向未修改的本機來源；結果副本加入 logging 後行號略有位移。

1. [TSU_Base.h:47](/home/emmanuel/projects/MQSim/src/ssd/TSU_Base.h:47)：`Prepare_for_transaction_submit()` 開啟提交群組，`Submit_transaction()` 暫放到 `transaction_receive_slots`。此時還沒對 NAND 發命令。
2. [TSU_OutofOrder.cpp:144](/home/emmanuel/projects/MQSim/src/ssd/TSU_OutofOrder.cpp:144)：`Schedule()` 根據 Type/Source 分流。USERIO/CACHE reads 進 `UserReadTRQueue[channel][chip]`，MAPPING/GC reads 有自己的 queues。這裡是 **per-channel/per-chip queue，不是 per-die queue**。
3. [TSU_OutofOrder.cpp:210](/home/emmanuel/projects/MQSim/src/ssd/TSU_OutofOrder.cpp:210)：channel 必須 IDLE，才輪詢其 chips；一旦派發使 channel BUSY，就停止找其他 chip。
4. [TSU_OutofOrder.cpp:227](/home/emmanuel/projects/MQSim/src/ssd/TSU_OutofOrder.cpp:227)：`service_read_transaction()` 選 queue。Mapping reads 優先；GC 是否 urgent 影響後續順序。本練習只有 USERIO reads。
5. [TSU_OutofOrder.cpp:301](/home/emmanuel/projects/MQSim/src/ssd/TSU_OutofOrder.cpp:301)：檢查 chip status。此 read-only 實驗只在 IDLE 派發；READING、DATA_OUT、WAIT_FOR_DATA_OUT 都落到 default→false。它沒有在 READING 狀態再找同 chip 的空閒 die。
6. [TSU_Base.cpp:72](/home/emmanuel/projects/MQSim/src/ssd/TSU_Base.cpp:72)：`issue_command_to_chip()` 從 queue 選同 die 的 transactions；不同 plane 且相同 PageID 才能在這段程式組成 multi-plane command。本練習固定一個 plane，排除這項變因。read 的 `transaction_is_ready()` 直接為 true，不是「硬體所有資源都空閒」的意思。
7. 此函式在第一次 `Send_command_to_chip()` 後立即 return。雖然外觀有 die loop，這次呼叫不會接著替另一個 die 發第二個 command。搭配第 5 點，形成這次觀察到的同 chip 串行化。

## 追 PHY／NAND：channel 何時 free，die 何時 busy？

[PHY Send_command_to_chip](/home/emmanuel/projects/MQSim/src/ssd/NVM_PHY_ONFI_NVDDR2.cpp:135) 設定 `dieBKE->Free=false`，建立 active command，將 chip 設成 CMD_IN，保留 channel 並註冊 `READ_CMD_ADDR_TRANSFERRED`。

[READ_CMD_ADDR_TRANSFERRED](/home/emmanuel/projects/MQSim/src/ssd/NVM_PHY_ONFI_NVDDR2.cpp:347) 發生時，`EndCMDXfer()` 觸發 [Flash_Chip::start_command_execution](/home/emmanuel/projects/MQSim/src/nvm_chip/flash_memory/Flash_Chip.cpp:102)，把該 die 的 array 狀態設為 BUSY，註冊 50 us 後的完成事件。若沒有待送的 interleaved commands，PHY 把 chip 設為 READING，但把 channel 設為 IDLE。

**因此 channel IDLE 與 die 正在讀 array 可以同時成立。**這時同 channel 的另一 chip 可以送 command；不是一定要等前一筆整個 read 結束。

Array 完成時，[Flash_Chip::finish_command_execution](/home/emmanuel/projects/MQSim/src/nvm_chip/flash_memory/Flash_Chip.cpp:130) 將 NAND array 的 `DieStatus` 設回 IDLE，發出 ready signal。PHY 的 [handle_ready_signal_from_chip](/home/emmanuel/projects/MQSim/src/ssd/NVM_PHY_ONFI_NVDDR2.cpp:492) 再檢查 channel：

- Channel 空閒：立即 `transfer_read_data_from_chip()`。
- Channel 忙碌：USERIO read 放到 **PHY 的 `WaitingReadTX[channel]`**。

**這是第二種 queue：TSU queue 等待開始 flash command；PHY queue 等待已讀好資料的 data-out。兩者不能混為一談。**

[transfer_read_data_from_chip](/home/emmanuel/projects/MQSim/src/ssd/NVM_PHY_ONFI_NVDDR2.cpp:625) 設 chip DATA_OUT、channel BUSY，註冊 `READ_DATA_TRANSFERRED`。在本組合中傳輸耗時 12.288 us。

[READ_DATA_TRANSFERRED](/home/emmanuel/projects/MQSim/src/ssd/NVM_PHY_ONFI_NVDDR2.cpp:397) 回報 transaction complete；active transactions 清空後 `ClearCommand()` 才設 PHY bookkeeping 的 `Free=true`，再更新 chip/channel 狀態。

注意兩種「die free」的不同：NAND array 的 BUSY 在 sensing 結束就解除；但 PHY 的 active command/data 尚未交付，bookkeeping 的 Free 要等 data-out 後。不能只看 Flash_Chip 中 DieStatus=IDLE 就推論 scheduler 會接受下一個 read。

## 誰觸發下一次派發？

- 新 transactions 到達：上層呼叫 `Schedule()`。
- Channel 釋放：[PHY 事件處理尾端](/home/emmanuel/projects/MQSim/src/ssd/NVM_PHY_ONFI_NVDDR2.cpp:438) 先服務 pending copyback／mapping read data／user read data／GC read data；沒有這些等待工作時，才 `broadcastChannelIdleSignal()`。
- [TSU_Base::handle_channel_idle_signal](/home/emmanuel/projects/MQSim/src/ssd/TSU_Base.cpp:47) 接到訊號，輪詢該 channel 的 chips，嘗試派發下一筆。
- [handle_chip_idle_signal](/home/emmanuel/projects/MQSim/src/ssd/TSU_Base.cpp:61) 也是已註冊的觸發路徑；先確認 channel 空閒再處理該 chip。這次普通 read 的主要喚醒路徑是 channel-idle callback。

這是事件驅動，不是每隔固定時間掃一次所有 requests。`SetStatus(IDLE)` 也不等於當下立刻喚醒 TSU：PHY 還可能先把 channel 交給等待中的 data-out。

## 具體走一次：同 channel、不同 chips

![Resource timeline](../../results/mqsim_pipeline_lab/resource_timeline.png)

| 時間（us） | 事件 |
|---:|---|
| 0 | R0/R1 一起送進 TSU；chip0 的 R0 取得 channel |
| 0.290 | R0 command 傳完，array 開始；channel 釋放，R1 開始傳 command |
| 0.580 | R1 array 開始；兩個 chips 的 array reads 重疊 |
| 50.290 | R0 array 完成，開始 data-out，占用 channel |
| 50.580 | R1 array 完成，但 channel 忙，進 `WaitingReadTX[0]` |
| 62.578 | R0 完成；PHY 直接開始 R1 data-out |
| 74.866 | R1 完成 |

在 0.580–50.290 us，channel 沒傳輸但兩個 arrays 都在工作。這不是 host 沒餵資料的證據。在 50.580–62.578 us，R1 等的是共享 channel，不是 NAND sensing。

## 分批 vs. 持續補入

同一組 16 個實體地址，順序固定；依序輪到 ch0/chip0、ch1/chip0、ch0/chip1、ch1/chip1，全部使用 die0/plane0，每四筆換 page。最大 outstanding 都是 4。

- `batch_gap0`：四筆全完成才送下一批，沒有額外 host delay。
- `batch_gap20us`：四筆全完成後再等 20 us，代表假設的 host think time，並非 DiskANN 量測值。
- `stream`：每完成一筆補一筆，沒有搜尋演算法的相依性。

為讓 completion callback 返回、完成 PHY 狀態清理後才重新提交，每次 refill 事件額外延後 1 ns；這是 harness 行為，不是 host 提交時間模型。

| 政策 | 完成 16 reads | 零 outstanding 時間 | 平均 outstanding |
|---|---:|---:|---:|
| batch_gap0 | 299.467 us | 0.003 us | 3.672 |
| batch_gap20us | 359.467 us | 60.003 us | 3.059 |
| stream | 299.464 us | 0 | 3.918 |

![Batches](../../results/mqsim_pipeline_lab/batch_vs_stream.png)

![Outstanding](../../results/mqsim_pipeline_lab/outstanding.png)

**stream 幾乎沒有贏過 batch_gap0。**第一批 R0 在 62.578 us 完成後，新 R4 在 62.579 us 就提交，但 channel 正忙著 R2 data-out，直到 74.866 us 才能發 R4 command。提前到達增加了 queue occupancy，沒有提前開始 array。PHY 的 pending data-out 優先處理加上這個均勻地址／延遲排列，使兩者時間軸幾乎相同。

相較 batch_gap20us，stream 省下約 60 us，主要是三次人為加入的 20 us 間隔。不能說是新 scheduler 帶來的 gain，也不能把這個數字當成 DiskANN 的實際加速比。把 outstanding 維持在 4，並不保證每個 die 一直工作。

## 驗證與輸出

`analyze.py` 已檢查：每筆完整事件順序、command/array/data 固定耗時、同 channel 傳輸不重疊、同 die array 不重疊、最大 outstanding 不超過 4、全部完成歸零、三個提交政策的實體地址序列完全相同，以及重疊／串行的預期關係。

- `*.csv`：逐事件時間（ns），附 request ID 與 channel/chip/die/plane/page。
- `summary.csv`：makespan、outstanding、channel busy 指標。channel busy 分母是**兩個已配置 channels × makespan**，不是單個活躍 channel，也不是 array utilization。
- `validation.json`：驗證結果。
- `manifest.json`：來源 commit、git status、所有來源檔 SHA256、模型假設。
- `instrumentation.patch`：只加入 logging，沒有改 TSU／PHY 排程邏輯。
- 四組圖：`read_cases`、`resource_timeline`、`batch_vs_stream`、`outstanding`，都有 PNG/SVG/PDF。

這組練習先回答 backend 的資源安排；要接回研究，下一步需注入真實 DiskANN 的 graph-work release dependencies 與實測 host think time，再比較 latency/recall。也應先明確選定並驗證 scheduler 的 die-level 支援，避免把模擬器限制誤認為硬體本質。
