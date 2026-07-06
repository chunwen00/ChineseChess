# 中國象棋（pygame + AI）

使用 **Python + pygame** 的中國象棋遊戲。

功能：

- **棋子規則**：馬拐馬腳、象田字且不能過河、炮翻山吃子、將帥不能對面、不可送將
- **AI 對手**：Minimax + Alpha-Beta 剪枝（含走法排序、快取），並有**時間上限**
- **流程**：將軍偵測、勝負判定（將/帥被吃 / 對方無路可走）
- **悔棋 / 重新開始**

## 環境需求

- Python 3.10+（建議 3.12+）
- Windows / macOS / Linux 皆可

## 安裝

```bash
pip install -r requirements.txt
```

## 執行

```bash
python main.py
```

- **拖曳走子**：按住棋子拖到合法落點後放開
- 頂部按鈕：**悔棋**、**重新開始**、**結束遊戲**

## AI 設定（強度 / 速度）

修改 `main.py` 的 `ai_config`：

```python
AIConfig(depth=2, use_tt=True, time_limit_sec=1.5)
```

## 檔案結構

- `main.py`：pygame 桌面版（繪圖、拖曳、按鈕 UI）
- `ai.py`：AI 模組（Minimax + Alpha-Beta、評估函數）
