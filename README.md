# 中國象棋（pygame 單機 + AI）

這是一個使用 **Python + pygame** 製作的中國象棋單機遊戲，支援：

- **棋盤繪製**：九宮格、楚河漢界
- **棋子規則**：馬拐馬腳、象田字且不能過河、炮翻山吃子、將帥不能對面、不可送將
- **操作**：滑鼠 **Drag & Drop** 拖曳走子
- **AI 對手**：Minimax + Alpha-Beta 剪枝（含走法排序、快取），並有**時間上限**
- **流程**：將軍偵測、勝負判定（將帥被吃 / 對方無路可走）
- **悔棋 / 重新開始**：頂部按鈕

## 環境需求

- Python 3.10+（建議 3.12+）
- Windows / macOS / Linux 皆可（本專案以 Windows 測試為主）

## 安裝

在專案目錄下執行：

```bash
pip install -r requirements.txt
```

## 執行

```bash
python main.py
```

## 操作方式

- **拖曳走子**：按住棋子拖到合法落點後放開
  - 若落點是敵方棋子 → 會吃子
  - 若落點不合法 → 會回彈到原位
- **悔棋**：點擊頂部按鈕「悔棋」
- **重新開始**：點擊頂部按鈕「重新開始」

## AI 設定（強度 / 速度）

在 `main.py` 的 `ai_config` 可調整：

- **depth**：搜尋深度（越大越強但越慢）
- **time_limit_sec**：單步思考時間上限（秒）

範例（更快）：

```python
ai_config = AIConfig(depth=2, use_tt=True, time_limit_sec=1.0)
```

範例（稍強）：

```python
ai_config = AIConfig(depth=3, use_tt=True, time_limit_sec=2.0)
```

## 檔案結構

- `main.py`：遊戲主程式（繪圖、事件、規則、流程判定、悔棋/重開 UI）
- `ai.py`：AI 模組（Minimax + Alpha-Beta、評估函數、時間上限）

