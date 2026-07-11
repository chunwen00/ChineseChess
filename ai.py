from __future__ import annotations

import time
import random
from dataclasses import dataclass
from typing import Any

# 盤面資料結構約定（與 main.py 相同）：
# pieces: {(col,row): (side,name)}
# - col: 0..8, row: 0..9
# - side: "red" / "black"
# - name: "車","馬","炮","象","士","將","卒" 或紅方的 "相","仕","帥","兵"


Piece = tuple[str, str]  # (side, name)
Pos = tuple[int, int]  # (col, row)
Move = tuple[Pos, Pos]  # (from_pos, to_pos)


@dataclass(frozen=True)
class AIConfig:
    depth: int = 4  # 預設搜尋深度 4 層（配合迭代加深 + TT，棋力明顯提升）
    use_tt: bool = True  # 是否啟用簡易置換表（快取）以加速
    time_limit_sec: float = 3.5  # 單步思考時間上限（秒）；逾時回傳目前已算出的最佳走法


@dataclass
class SearchBudget:
    """
    搜尋時間預算：
    - 超過 deadline 就停止繼續展開（避免 AI 思考太久造成卡頓）
    - choose_best_move 會回傳「截止前」已評估到的最佳根走法
    """

    deadline: float | None = None
    timed_out: bool = False

    @classmethod
    def from_limit(cls, seconds: float) -> SearchBudget:
        if seconds <= 0:
            return cls(deadline=None)
        return cls(deadline=time.perf_counter() + seconds)

    def expired(self) -> bool:
        if self.deadline is None:
            return False
        if time.perf_counter() >= self.deadline:
            self.timed_out = True
            return True
        return False


# 基礎分（你指定）
BASE_VALUE: dict[str, int] = {
    "車": 90,
    "馬": 40,
    "炮": 45,
    "象": 20,
    "士": 20,
    "將": 10_000,  # 將帥本身給極大值（避免搜尋時無視保護主將）
    "卒": 10,
}


# ----------------------------
# 位置分表（Piece-Square Tables, PST）
# ----------------------------
# 座標約定與 main.py 相同：
# - row=0 在上方（黑方底線），row=9 在下方（紅方底線）
# - col=0..8 由左到右
#
# 表一律以「黑方視角」撰寫（黑方往下攻、過河是 row 變大）。
# 評估紅方棋子時，把 row 鏡射成 9-row，即可共用同一張表。
#
# 為什麼位置分能提升棋力？
# - 只看子力時，AI 不知道「車出庫、馬出槽、兵過河」比「窩在底線」好。
# - PST 把「常見好位置」變成加分，讓搜尋在同樣深度下更偏好合理布局。

# 車：鼓勵佔中路/開線，進入對方半場加分；邊角略扣
PST_ROOK: list[list[int]] = [
    [ 6,  6,  6,  8, 10,  8,  6,  6,  6],  # row0 底線：能橫掃也不錯
    [ 4,  4,  6,  8, 10,  8,  6,  4,  4],
    [ 4,  6,  8, 10, 12, 10,  8,  6,  4],
    [ 6,  8, 10, 12, 14, 12, 10,  8,  6],
    [ 8, 10, 12, 14, 16, 14, 12, 10,  8],  # 河界附近
    [10, 12, 14, 16, 18, 16, 14, 12, 10],  # 過河後更強
    [12, 14, 16, 18, 20, 18, 16, 14, 12],
    [12, 14, 16, 18, 20, 18, 16, 14, 12],
    [10, 12, 14, 16, 18, 16, 14, 12, 10],
    [ 8, 10, 12, 14, 16, 14, 12, 10,  8],
]

# 馬：鼓勵出庫、佔中，邊線（尤其底角）較差；過河略加
PST_HORSE: list[list[int]] = [
    [-6, -4,  0,  2,  2,  2,  0, -4, -6],
    [-4,  0,  4,  6,  6,  6,  4,  0, -4],
    [ 0,  4,  8, 10, 10, 10,  8,  4,  0],
    [ 2,  6, 10, 12, 12, 12, 10,  6,  2],
    [ 2,  6, 10, 12, 14, 12, 10,  6,  2],
    [ 4,  8, 12, 14, 16, 14, 12,  8,  4],
    [ 4,  8, 12, 14, 16, 14, 12,  8,  4],
    [ 2,  6, 10, 12, 14, 12, 10,  6,  2],
    [ 0,  4,  8, 10, 10, 10,  8,  4,  0],
    [-4,  0,  2,  4,  4,  4,  2,  0, -4],
]

# 炮：中路與對方半場較佳；常鼓勵「炮架」相關的中前排
PST_CANNON: list[list[int]] = [
    [ 0,  2,  4,  6,  8,  6,  4,  2,  0],
    [ 2,  4,  6,  8, 10,  8,  6,  4,  2],
    [ 4,  6,  8, 10, 12, 10,  8,  6,  4],
    [ 4,  6,  8, 10, 12, 10,  8,  6,  4],
    [ 6,  8, 10, 12, 14, 12, 10,  8,  6],
    [ 6,  8, 10, 12, 14, 12, 10,  8,  6],
    [ 8, 10, 12, 14, 16, 14, 12, 10,  8],
    [ 8, 10, 12, 14, 16, 14, 12, 10,  8],
    [ 6,  8, 10, 12, 14, 12, 10,  8,  6],
    [ 2,  4,  6,  8, 10,  8,  6,  4,  2],
]

# 卒/兵：前進加分，過河大幅加分，逼近九宮最高
PST_PAWN: list[list[int]] = [
    [ 0,  0,  0,  0,  0,  0,  0,  0,  0],  # 己方底線幾乎沒有卒
    [ 0,  0,  0,  0,  0,  0,  0,  0,  0],
    [ 0,  0,  0,  0,  0,  0,  0,  0,  0],
    [ 2,  0,  4,  0,  6,  0,  4,  0,  2],  # 開局卒線
    [ 6,  4,  8,  6, 10,  6,  8,  4,  6],  # 逼近河界
    [12, 12, 14, 16, 18, 16, 14, 12, 12],  # 過河
    [16, 16, 18, 22, 26, 22, 18, 16, 16],
    [20, 20, 24, 28, 32, 28, 24, 20, 20],
    [24, 24, 28, 34, 40, 34, 28, 24, 24],  # 逼宮
    [18, 18, 22, 28, 34, 28, 22, 18, 18],
]

# 士：九宮內中央略高，鼓勵留在九宮護衛
PST_ADVISOR: list[list[int]] = [
    [ 0,  0,  0,  8, 12,  8,  0,  0,  0],
    [ 0,  0,  0, 10, 14, 10,  0,  0,  0],
    [ 0,  0,  0,  8, 12,  8,  0,  0,  0],
    [ 0,  0,  0,  0,  0,  0,  0,  0,  0],
    [ 0,  0,  0,  0,  0,  0,  0,  0,  0],
    [ 0,  0,  0,  0,  0,  0,  0,  0,  0],
    [ 0,  0,  0,  0,  0,  0,  0,  0,  0],
    [ 0,  0,  0,  0,  0,  0,  0,  0,  0],
    [ 0,  0,  0,  0,  0,  0,  0,  0,  0],
    [ 0,  0,  0,  0,  0,  0,  0,  0,  0],
]

# 象：留在己方半場的合理象位；過河無意義（規則也不允許）
PST_ELEPHANT: list[list[int]] = [
    [ 0,  0,  6,  0,  0,  0,  6,  0,  0],
    [ 0,  0,  0,  0,  0,  0,  0,  0,  0],
    [ 4,  0,  0,  0, 10,  0,  0,  0,  4],
    [ 0,  0,  0,  0,  0,  0,  0,  0,  0],
    [ 0,  0,  6,  0,  0,  0,  6,  0,  0],
    [ 0,  0,  0,  0,  0,  0,  0,  0,  0],
    [ 0,  0,  0,  0,  0,  0,  0,  0,  0],
    [ 0,  0,  0,  0,  0,  0,  0,  0,  0],
    [ 0,  0,  0,  0,  0,  0,  0,  0,  0],
    [ 0,  0,  0,  0,  0,  0,  0,  0,  0],
]

# 將：九宮內略偏後、居中較安全；避免無謂前出
PST_KING: list[list[int]] = [
    [ 0,  0,  0,  8, 12,  8,  0,  0,  0],
    [ 0,  0,  0,  6, 10,  6,  0,  0,  0],
    [ 0,  0,  0,  2,  4,  2,  0,  0,  0],
    [ 0,  0,  0,  0,  0,  0,  0,  0,  0],
    [ 0,  0,  0,  0,  0,  0,  0,  0,  0],
    [ 0,  0,  0,  0,  0,  0,  0,  0,  0],
    [ 0,  0,  0,  0,  0,  0,  0,  0,  0],
    [ 0,  0,  0,  0,  0,  0,  0,  0,  0],
    [ 0,  0,  0,  0,  0,  0,  0,  0,  0],
    [ 0,  0,  0,  0,  0,  0,  0,  0,  0],
]

PST_BY_KIND: dict[str, list[list[int]]] = {
    "車": PST_ROOK,
    "馬": PST_HORSE,
    "炮": PST_CANNON,
    "卒": PST_PAWN,
    "士": PST_ADVISOR,
    "象": PST_ELEPHANT,
    "將": PST_KING,
}


def position_bonus(side: str, kind: str, col: int, row: int) -> int:
    """
    查詢棋子在 (col,row) 的位置加分。

    - 表以黑方視角定義；紅方用 row' = 9-row 鏡射。
    - 超出範圍或未知棋種回傳 0（防禦性寫法）。
    """
    table = PST_BY_KIND.get(kind)
    if table is None:
        return 0
    eval_row = row if side == "black" else 9 - row
    if not (0 <= col <= 8 and 0 <= eval_row <= 9):
        return 0
    return table[eval_row][col]


# ----------------------------
# Zobrist Hashing（置換表用雜湊 key）
# ----------------------------
# 目標：
# - 用 64-bit 隨機數為「(格子, 棋子種類)」編碼
# - 整盤的 zobrist_key 是所有棋子的 XOR（異或）總和
# - 移動棋子/吃子時，只需 XOR 幾個數字即可 O(1) 更新 key，不需要重新掃描全盤
#
# 為什麼 XOR 可以 O(1) 更新？
# - XOR 有「自反」性質：x ^ x = 0，且 x ^ 0 = x
# - 當某棋子從 A 格移到 B 格：
#   1) key ^= zobrist[A][piece]   （把舊位置的棋子移除）
#   2) key ^= zobrist[B][piece]   （把新位置的棋子加入）
#   若有吃子，再做一次移除：
#   3) key ^= zobrist[B][captured_piece]
# - 因為同一個隨機數 XOR 兩次會抵消，所以只要 XOR 變動的項即可維持正確雜湊值


def _piece_index(side: str, name: str) -> int:
    """
    將 (side, name) 映射到 [0..13] 共 14 種棋子索引。

    需求對應：
    - 棋盤 10x9
    - 棋子種類 14：紅黑各 7 種（車、馬、炮、象/相、士/仕、將/帥、卒/兵）

    備註：
    - 我們用 normalize_kind 把紅方特有字形統一（相->象、仕->士、帥->將、兵->卒）
    - 索引規則：黑方 0..6；紅方 7..13（方便區分陣營）
    """
    kind = normalize_kind(name)
    order = ["車", "馬", "炮", "象", "士", "將", "卒"]
    base = order.index(kind)  # 若遇到未知棋子，讓程式直接噴錯以便及早發現資料不一致
    return base if side == "black" else 7 + base


@dataclass
class TTEntry:
    """
    置換表（Transposition Table, TT）條目。

    flag 說明（標準 alpha-beta TT 寫法）：
    - "EXACT"：精確值（在該深度下完整搜索得到的 minimax 分數）
    - "LOWER"：下界（fail-high，真值 >= value）
    - "UPPER"：上界（fail-low，真值 <= value）
    """

    depth: int
    value: int
    flag: str  # "EXACT" | "LOWER" | "UPPER"


class ZobristHasher:
    """
    Zobrist Hashing 初始化器：
    - zobrist_table[10][9][14]：對應 (row, col, piece_index)
    - side_to_move_key：輪到哪一方行棋也要納入 key（避免同一盤面但輪到不同方被混淆）
    """

    def __init__(self, seed: int | None = None) -> None:
        rng = random.Random(seed)
        # 需求指定三維陣列大小：10x9x14（row 0..9, col 0..8, piece 0..13）
        self.zobrist_table: list[list[list[int]]] = [
            [[rng.getrandbits(64) for _ in range(14)] for _ in range(9)] for _ in range(10)
        ]
        # side_to_move_key：通常只需 1 個隨機數，當輪到黑/紅切換時 XOR 一次即可
        self.side_to_move_key: int = rng.getrandbits(64)

    def compute_key(self, pieces: dict[Pos, Piece], side_to_play: str) -> int:
        """初始化全盤 key（僅在根節點或重置時使用；搜尋中靠 XOR 動態更新）。"""
        key = 0
        for (col, row), (side, name) in pieces.items():
            idx = _piece_index(side, name)
            key ^= self.zobrist_table[row][col][idx]
        # 把「輪到誰」也納入 key：約定 side_to_play == "black" 時 XOR side_to_move_key
        if side_to_play == "black":
            key ^= self.side_to_move_key
        return key

    def xor_piece(self, key: int, pos: Pos, piece: Piece) -> int:
        """在 key 上 XOR 一個棋子（用於加入或移除；同一項 XOR 兩次會抵消）。"""
        col, row = pos
        idx = _piece_index(piece[0], piece[1])
        return key ^ self.zobrist_table[row][col][idx]

    def xor_side(self, key: int) -> int:
        """切換行棋方（每走一步 XOR 一次 side_to_move_key）。"""
        return key ^ self.side_to_move_key


def make_move(
    pieces: dict[Pos, Piece],
    mv: Move,
    *,
    zobrist_key: int,
    hasher: ZobristHasher,
) -> tuple[Piece | None, int]:
    """
    原地走子（會修改 pieces），並用 XOR 在 O(1) 更新 zobrist_key。

    回傳：
    - captured：若有吃子則為被吃棋子；否則 None
    - new_key：更新後的 zobrist_key（已包含 side 切換）
    """
    src, dst = mv
    moving = pieces.get(src)
    if moving is None:
        return None, zobrist_key

    captured = pieces.get(dst)

    # 1) 從 src 移除 moving（XOR 掉舊位置）
    key = hasher.xor_piece(zobrist_key, src, moving)
    # 2) 若 dst 有敵子被吃，先從 dst 移除 captured（XOR 掉被吃棋子）
    if captured is not None:
        key = hasher.xor_piece(key, dst, captured)
        pieces.pop(dst, None)
    # 3) 把 moving 加到 dst（XOR 加上新位置）
    key = hasher.xor_piece(key, dst, moving)

    # 實際移動
    pieces.pop(src, None)
    pieces[dst] = moving

    # 4) 行棋方切換（XOR 一次）
    key = hasher.xor_side(key)
    return captured, key


def unmake_move(
    pieces: dict[Pos, Piece],
    mv: Move,
    *,
    captured: Piece | None,
    zobrist_key: int,
    hasher: ZobristHasher,
) -> int:
    """
    回復 make_move（原地回復 pieces），並用 XOR 在 O(1) 回復 zobrist_key。
    - captured 需由 make_move 回傳（被吃棋子）

    回傳：回復後的 zobrist_key（已包含 side 切回）
    """
    src, dst = mv
    moving = pieces.get(dst)
    if moving is None:
        return zobrist_key

    # 1) 先把 side 切回（XOR 一次）
    key = hasher.xor_side(zobrist_key)

    # 2) 從 dst 移除 moving（XOR 掉新位置）
    key = hasher.xor_piece(key, dst, moving)
    # 3) 把 moving 加回 src（XOR 加上舊位置）
    key = hasher.xor_piece(key, src, moving)

    # 實際回復移動
    pieces.pop(dst, None)
    pieces[src] = moving

    # 4) 若之前有吃子，把 captured 放回 dst（並 XOR 回去）
    if captured is not None:
        pieces[dst] = captured
        key = hasher.xor_piece(key, dst, captured)

    return key


def board_key(pieces: dict[Pos, Piece]) -> tuple[Any, ...]:
    """
    把盤面轉成可 hash 的 key，供置換表（transposition table, TT）快取用。
    - 用排序後的 items 讓 key 在同一局面下穩定一致
    - 深度小（3）時這種 key 的成本可接受，能顯著減少重複局面評估
    """
    return tuple(sorted(((c, r, s, n) for (c, r), (s, n) in pieces.items())))


def move_order_score(
    pieces: dict[Pos, Piece],
    mv: Move,
    side_to_play: str,
) -> int:
    """
    走法排序的啟發式分數（越大越優先展開）：
    - 只用「吃子」資訊做排序（O(1)），避免在排序時反覆呼叫 get_valid_moves 造成極慢/卡死
    - 使用 MVV-LVA（Most Valuable Victim - Least Valuable Attacker）：
        分數 = 被吃棋子價值 - 攻擊棋子價值
      直覺：越「用小子換大子」越優先（例如：卒吃車 > 車吃卒）
    - 先展開高價值吃子 → Alpha-Beta 更容易早早找到更緊的 alpha/beta 界限，剪枝更大量
    """
    src, dst = mv
    captured = pieces.get(dst)
    if captured is None or captured[0] == side_to_play:
        return 0  # 非吃子（或吃到己方不可能）→ 不加分

    attacker = pieces.get(src)
    if attacker is None:
        return 0

    victim_kind = normalize_kind(captured[1])
    attacker_kind = normalize_kind(attacker[1])
    victim_value = BASE_VALUE.get(victim_kind, 0)
    attacker_value = BASE_VALUE.get(attacker_kind, 0)

    # 讓「吃子」整體都排在「不吃子」之前：加上一個大常數當作「吃子標記」
    # 再用 MVV-LVA 做細部排序。
    return 10_000 + (victim_value - attacker_value)


def sort_moves(
    moves: list[Move],
    *,
    pieces: dict[Pos, Piece],
    side_to_play: str,
    history_table: list[list[int]] | None = None,
) -> list[Move]:
    """
    走法排序（用於 Alpha-Beta）：

    為什麼要排序？
    - Alpha-Beta 的剪枝效率高度依賴「先找到好走法」的速度。
    - 如果先展開較強的走法（特別是高價值吃子），更快更新 alpha/beta，
      後續較差分支就更容易觸發 `alpha >= beta` 而被剪枝，整體節點數大幅下降。

    這裡使用兩種排序訊號（由強到弱）：
    1) **吃子走法**：MVV-LVA（被吃價值 - 攻擊價值）由高到低
    2) **非吃子走法**：History Heuristic（歷史啟發表）由高到低

    History Heuristic 的直覺（中文解釋）：
    - 在 Alpha-Beta 的搜尋中，某些「普通走法（非吃子）」常常在其他分支被證明是好棋，
      例如它們曾經讓對手分支很快發生剪枝（代表這步很有威力/很難應對）。
    - 我們把這些「在其他分支有用的好棋」記到 history_table[from][to] 裡，
      下次在不同局面/分支遇到同樣的 from->to 普通走法時，就會優先展開，
      讓 alpha/beta 更早收斂、剪枝更多節點、搜尋更快。
    """

    def _pos_index(p: Pos) -> int:
        # 棋盤 9x10 = 90 個落子點，index = row*9 + col
        c, r = p
        return r * 9 + c

    def _score(mv: Move) -> int:
        # 先判斷是否吃子
        src, dst = mv
        captured = pieces.get(dst)
        if captured is not None and captured[0] != side_to_play:
            # 吃子：用 MVV-LVA，並加上大常數確保「任何吃子」都排在非吃子前面
            return move_order_score(pieces, mv, side_to_play)

        # 非吃子：使用歷史啟發表（若未提供就視為 0）
        if history_table is None:
            return 0
        return history_table[_pos_index(src)][_pos_index(dst)]

    return sorted(moves, key=_score, reverse=True)


def normalize_kind(name: str) -> str:
    """
    把紅方特有名稱轉成統一棋種：
    - 相->象, 仕->士, 帥->將, 兵->卒
    """
    if name == "相":
        return "象"
    if name == "仕":
        return "士"
    if name == "帥":
        return "將"
    if name == "兵":
        return "卒"
    return name


def evaluate_position(
    pieces: dict[Pos, Piece],
    ai_side: str,
    get_valid_moves_func,
    kings_facing_func,
) -> int:
    """
    評估函數（分數越大越有利於 ai_side）。

    評估項目：
    - 基礎分：車=90, 馬=40, 炮=45, 象=20, 士=20, 卒=10（將/帥給極大值）
    - 位置分（PST）：車馬炮兵士象將依落點加分/扣分
    - 大子壓將：車/炮與敵將同列/同行加分（鼓勵控制與攻殺）
    - 防守子力：己方士象尚在加分（鼓勵留士象保將）
    - 將帥受威脅（被將軍）加減分
    - 將帥對面：嚴重懲罰
    """
    score = 0
    opp = "red" if ai_side == "black" else "black"

    # ----------------------------
    # 1) 基礎分 + 位置分（PST）+ 防守子力
    # ----------------------------
    advisors = {ai_side: 0, opp: 0}
    elephants = {ai_side: 0, opp: 0}
    for (col, row), (side, name) in pieces.items():
        kind = normalize_kind(name)
        base = BASE_VALUE.get(kind, 0)
        # 位置分：鼓勵出庫、佔中、過河、逼宮等「好位置」
        pst = position_bonus(side, kind, col, row)
        value = base + pst
        score += value if side == ai_side else -value
        if kind == "士":
            advisors[side] += 1
        elif kind == "象":
            elephants[side] += 1

    # 士象齊全較安全：每位士/象約 +6（相對對手）
    score += (advisors[ai_side] - advisors[opp]) * 6
    score += (elephants[ai_side] - elephants[opp]) * 6

    # ----------------------------
    # 2) 大子壓將（便宜且有效的攻勢啟發式）
    # ----------------------------
    # 若車/炮與敵將同直線，常形成將軍/抽將/牽制威脅 → 給小加分。
    # 不做完整攻擊計算（避免評估函數太慢），只看行列對齊。
    for side, sign in ((ai_side, 1), (opp, -1)):
        king_pos = find_king_pos(pieces, "red" if side == "black" else "black")
        if king_pos is None:
            continue
        kc, kr = king_pos
        for (col, row), (s, name) in pieces.items():
            if s != side:
                continue
            kind = normalize_kind(name)
            if kind == "車":
                if col == kc:
                    score += 10 * sign
                if row == kr:
                    score += 8 * sign
            elif kind == "炮":
                if col == kc:
                    score += 7 * sign
                if row == kr:
                    score += 6 * sign
            elif kind == "馬":
                # 馬靠近敵將九宮附近略加分（粗略距離）
                dist = abs(col - kc) + abs(row - kr)
                if dist <= 3:
                    score += 3 * sign

    # ----------------------------
    # 3) 將帥受威脅扣分（被將軍）
    # ----------------------------
    # 加大權重：寧可先解將/造將，也不要貪子漏殺
    if is_in_check(pieces, ai_side, get_valid_moves_func):
        score -= 160
    if is_in_check(pieces, opp, get_valid_moves_func):
        score += 140

    # ----------------------------
    # 4) 將帥對面：視為嚴重非法（大幅扣分）
    # ----------------------------
    if kings_facing_func(pieces):
        score -= 2_000

    return score


def find_king_pos(pieces: dict[Pos, Piece], side: str) -> Pos | None:
    """找出某一方將/帥的位置。"""
    for pos, (s, name) in pieces.items():
        if s != side:
            continue
        if (side == "black" and name == "將") or (side == "red" and name == "帥"):
            return pos
    return None


def is_in_check(
    pieces: dict[Pos, Piece],
    side: str,
    get_valid_moves_func,
) -> bool:
    """
    判斷 side 是否被將軍：
    - 找到 side 的將/帥位置
    - 生成對方所有棋子的合法走法
    - 若任何一步能走到（吃到）將/帥位置，則為被將軍
    """
    king_pos = find_king_pos(pieces, side)
    if king_pos is None:
        return True  # 沒有將/帥（已被吃）→ 視為極端不利

    enemy = "red" if side == "black" else "black"
    for pos, pc in pieces.items():
        if pc[0] != enemy:
            continue
        moves = get_valid_moves_func(pc, pos, pieces)
        if king_pos in moves:
            return True
    return False


def apply_move(pieces: dict[Pos, Piece], mv: Move) -> dict[Pos, Piece]:
    """回傳走一步之後的新盤面（不修改原盤面）。"""
    src, dst = mv
    new_pieces = dict(pieces)
    moving = new_pieces.pop(src, None)
    if moving is None:
        return new_pieces
    new_pieces[dst] = moving  # 若 dst 原有敵子，直接覆蓋即為吃子
    return new_pieces


def generate_all_moves(
    side: str,
    pieces: dict[Pos, Piece],
    get_valid_moves_func,
    *,
    history_table: list[list[int]] | None = None,
) -> list[Move]:
    """生成 side 的所有合法走法（from->to）。"""
    all_moves: list[Move] = []
    for pos, pc in pieces.items():
        if pc[0] != side:
            continue
        for dst in get_valid_moves_func(pc, pos, pieces):
            all_moves.append((pos, dst))
    # 走法排序（非常重要）：提升 Alpha-Beta 剪枝效果，讓 AI 更快也更強
    return sort_moves(all_moves, pieces=pieces, side_to_play=side, history_table=history_table)


def choose_best_move(
    pieces: dict[Pos, Piece],
    ai_side: str,
    get_valid_moves_func,
    kings_facing_func,
    config: AIConfig | None = None,
) -> Move | None:
    """
    用 Minimax + Alpha-Beta 剪枝選出 ai_side 最佳一步。

    強化點：迭代加深（Iterative Deepening）
    - 由淺到深：depth=1 → 2 → ... → config.depth
    - 每一層完整算完才採用該層最佳走法（逾時則保留上一層結果，避免半成品分數誤導）
    - 上一層的走法分數用來重排下一層根節點走法順序 → 剪枝更兇、更深更快

    Alpha-Beta 剪枝如何減少運算量（中文說明）：
    - 在 Minimax 中，MAX 節點要找「子節點中最大的分數」，MIN 節點要找「最小的分數」。
    - Alpha 表示「目前 MAX 已知的最佳(最大)下界」，Beta 表示「目前 MIN 已知的最佳(最小)上界」。
    - 當在搜尋某分支時發現 alpha >= beta，代表這個分支不可能改變最終決策，
      因此可以「直接停止」繼續展開子節點（剪枝）。
    """
    if config is None:
        config = AIConfig()

    # 若棋局已結束（將/帥不存在），就不需要走
    if find_king_pos(pieces, "black") is None or find_king_pos(pieces, "red") is None:
        return None

    best_move: Move | None = None
    # 置換表（Transposition Table）：用 zobrist_key 當 key（O(1)），條目含 depth + 界限旗標
    transposition_table: dict[int, TTEntry] = {}
    hasher = ZobristHasher()  # 初始化 Zobrist 隨機表（10x9x14）與 side_to_move_key
    # 歷史啟發表（History Heuristic）：跨迭代加深層共用，越搜越好用
    history_table: list[list[int]] = [[0 for _ in range(90)] for _ in range(90)]
    budget = SearchBudget.from_limit(config.time_limit_sec)  # 建立本步時間預算

    root_moves = generate_all_moves(ai_side, pieces, get_valid_moves_func, history_table=history_table)
    if not root_moves:
        return None

    # 初始化全盤 zobrist_key（僅在根節點做一次；後續靠 make/unmake_move XOR 動態更新）
    root_key = hasher.compute_key(pieces, side_to_play=ai_side)

    max_depth = max(1, config.depth)
    for depth in range(1, max_depth + 1):
        if budget.expired():
            break

        iteration_best: Move | None = None
        iteration_score = -10**18
        scored: list[tuple[int, Move]] = []
        incomplete = False

        for mv in root_moves:
            if budget.expired():
                incomplete = True
                break
            captured, child_key = make_move(pieces, mv, zobrist_key=root_key, hasher=hasher)
            s = minimax(
                pieces=pieces,
                depth=depth - 1,
                maximizing=False,
                ai_side=ai_side,
                alpha=-10**18,
                beta=10**18,
                get_valid_moves_func=get_valid_moves_func,
                kings_facing_func=kings_facing_func,
                transposition_table=transposition_table,
                hasher=hasher,
                zobrist_key=child_key,
                history_table=history_table,
                use_tt=config.use_tt,
                budget=budget,
            )
            root_key = unmake_move(
                pieces,
                mv,
                captured=captured,
                zobrist_key=child_key,
                hasher=hasher,
            )
            scored.append((s, mv))
            if s > iteration_score:
                iteration_score = s
                iteration_best = mv

        # 只有「完整層」才更新正式最佳走法（逾時半層不採用，避免誤判）
        if not incomplete and iteration_best is not None:
            best_move = iteration_best
            # 依本層分數重排根走法：下一層先搜好棋 → Alpha-Beta 剪得更多
            scored.sort(key=lambda x: x[0], reverse=True)
            root_moves = [mv for _, mv in scored]
        elif best_move is None and iteration_best is not None:
            # 連第一層都沒完整算完：至少先用目前最好的
            best_move = iteration_best

        if budget.expired():
            break

    if best_move is None:
        best_move = root_moves[0]
    return best_move


def _child_search_depth(depth: int, gives_check: bool) -> int:
    """
    計算子節點剩餘深度，並在「將軍」時做延伸（Check Extension）。

    - 正常：depth - 1
    - 若此步造成將軍：多看 1 層（回傳 depth），避免漏掉連將/殺棋
    - 限制：只在 depth <= 4 時延伸，防止將軍延伸無限膨脹
    """
    next_depth = depth - 1
    if gives_check and depth <= 4:
        next_depth = depth  # 等於 depth-1+1
    return next_depth


def minimax(
    pieces: dict[Pos, Piece],
    depth: int,
    maximizing: bool,
    ai_side: str,
    alpha: int,
    beta: int,
    get_valid_moves_func,
    kings_facing_func,
    transposition_table: dict[int, TTEntry] | None = None,
    hasher: ZobristHasher | None = None,
    zobrist_key: int = 0,
    history_table: list[list[int]] | None = None,
    use_tt: bool = True,
    budget: SearchBudget | None = None,
) -> int:
    """Minimax 主遞迴（含 Alpha-Beta 剪枝 + 可選時間上限）。"""
    # ----------------------------
    # 靜態搜尋（Quiescence Search, Q-search）
    # ----------------------------
    # 目的：避免「地平線效應」（horizon effect）
    # - 傳統 Minimax 在 depth==0 直接回傳 evaluate_position。
    # - 但如果 depth==0 的盤面正好存在「連續互吃」的戰術（例如：你吃我車、我吃你炮...），
    #   直接評估會把局面「停在半套交換中」，導致分數嚴重失真。
    #
    # 做法：當主搜尋深度走到 0，不立刻回傳評估，而是只展開「吃子走法」：
    # - 若當前方有吃子，就繼續往下看（但只看吃子，不看安靜走法）
    # - 直到「沒有任何吃子」或到達 Q-search 的最大深度（避免無限展開）為止
    #
    # 注意：這裡的 quiescence_search 依照你的需求採用簽名 (alpha, beta, depth)。
    # 盤面、輪到誰、評估與走法生成函式則由外層 minimax 閉包提供。
    def quiescence_search(alpha: int, beta: int, depth: int) -> int:
        """
        靜態搜尋（只看吃子）。

        依你要求保留簽名 `(alpha, beta, depth)`；
        實際遞迴時會由內部 helper `_qsearch(...)` 帶入盤面與輪到哪一方，
        避免在展開吃子時「又回到主搜尋」而造成深度重置/無限遞迴。
        """

        def _qsearch(
            pieces_q: dict[Pos, Piece],
            maximizing_q: bool,
            alpha_q: int,
            beta_q: int,
            depth_q: int,
            zobrist_key_q: int,
        ) -> int:
            """
            真正的 Q-search 遞迴。

            遞迴終止條件（非常重要）：
            1) depth_q <= 0：已到靜態搜尋最大深度 → 回傳靜態評估（stand pat）
            2) 當前方沒有任何「吃子」走法 → 局面安靜（quiet）→ 回傳靜態評估（stand pat）
            3) 時間到（budget.expired）→ 立即截斷回傳評估，確保 UI 不會卡住

            alpha/beta 的更新與剪枝：
            - maximizing 節點：若 stand_pat >= beta_q 可直接 beta-cut
            - minimizing 節點：若 stand_pat <= alpha_q 可直接 alpha-cut
            """
            if budget is not None and budget.expired():
                return evaluate_position(pieces_q, ai_side, get_valid_moves_func, kings_facing_func)

            # 置換表查詢（Q-search 也可以使用，但深度是 depth_q）
            if use_tt and transposition_table is not None:
                entry = transposition_table.get(zobrist_key_q)
                if entry is not None and entry.depth >= depth_q:
                    if entry.flag == "EXACT":
                        return entry.value
                    if entry.flag == "LOWER" and entry.value > alpha_q:
                        alpha_q = entry.value
                    elif entry.flag == "UPPER" and entry.value < beta_q:
                        beta_q = entry.value
                    if alpha_q >= beta_q:
                        return entry.value

            # stand pat：不走子、直接評估目前盤面
            stand_pat = evaluate_position(pieces_q, ai_side, get_valid_moves_func, kings_facing_func)

            # 終止條件 1：已到 Q-search 最大深度
            if depth_q <= 0:
                return stand_pat

            side_to_play_q = ai_side if maximizing_q else ("red" if ai_side == "black" else "black")

            # 生成「只吃子」走法（Capture-only）
            capture_moves: list[Move] = []
            for src, pc in pieces_q.items():
                if pc[0] != side_to_play_q:
                    continue
                for dst in get_valid_moves_func(pc, src, pieces_q):
                    captured = pieces_q.get(dst)
                    if captured is not None and captured[0] != side_to_play_q:
                        capture_moves.append((src, dst))

            # 終止條件 2：沒有吃子走法 → 局面安靜
            if not capture_moves:
                return stand_pat

            # 在 Q-search 只展開吃子，因此排序只需要 MVV-LVA（history 對吃子不適用）
            capture_moves = sort_moves(capture_moves, pieces=pieces_q, side_to_play=side_to_play_q, history_table=None)

            alpha_orig, beta_orig = alpha_q, beta_q
            if maximizing_q:
                # maximizing：先用 stand_pat 更新 alpha
                if stand_pat >= beta_q:
                    return beta_q  # beta-cut
                if stand_pat > alpha_q:
                    alpha_q = stand_pat

                for mv in capture_moves:
                    assert hasher is not None
                    captured, child_key = make_move(pieces_q, mv, zobrist_key=zobrist_key_q, hasher=hasher)
                    score = _qsearch(pieces_q, False, alpha_q, beta_q, depth_q - 1, child_key)
                    zobrist_key_q = unmake_move(
                        pieces_q,
                        mv,
                        captured=captured,
                        zobrist_key=child_key,
                        hasher=hasher,
                    )
                    if score > alpha_q:
                        alpha_q = score
                    if alpha_q >= beta_q:
                        break  # 剪枝
                # TT 回填（Q-search）
                if use_tt and transposition_table is not None:
                    flag = "EXACT"
                    if alpha_q <= alpha_orig:
                        flag = "UPPER"
                    elif alpha_q >= beta_orig:
                        flag = "LOWER"
                    transposition_table[zobrist_key_q] = TTEntry(depth=depth_q, value=alpha_q, flag=flag)
                return alpha_q

            # minimizing：先用 stand_pat 更新 beta
            if stand_pat <= alpha_q:
                return alpha_q  # alpha-cut
            if stand_pat < beta_q:
                beta_q = stand_pat

            for mv in capture_moves:
                assert hasher is not None
                captured, child_key = make_move(pieces_q, mv, zobrist_key=zobrist_key_q, hasher=hasher)
                score = _qsearch(pieces_q, True, alpha_q, beta_q, depth_q - 1, child_key)
                zobrist_key_q = unmake_move(
                    pieces_q,
                    mv,
                    captured=captured,
                    zobrist_key=child_key,
                    hasher=hasher,
                )
                if score < beta_q:
                    beta_q = score
                if alpha_q >= beta_q:
                    break  # 剪枝
            # TT 回填（Q-search）
            if use_tt and transposition_table is not None:
                flag = "EXACT"
                if beta_q <= alpha_orig:
                    flag = "UPPER"
                elif beta_q >= beta_orig:
                    flag = "LOWER"
                transposition_table[zobrist_key_q] = TTEntry(depth=depth_q, value=beta_q, flag=flag)
            return beta_q

        return _qsearch(pieces, maximizing, alpha, beta, depth, zobrist_key)

    # 時間上限：逾時就用當前局面評估分數當作截斷值（讓搜尋能盡快返回）
    if budget is not None and budget.expired():
        return evaluate_position(pieces, ai_side, get_valid_moves_func, kings_facing_func)

    # 置換表查詢（在 alpha-beta 一開始做，命中就直接回傳或縮小界限）
    # 只要命中條目且 entry.depth >= depth，代表「至少同等深度」已完整計算過，可安全使用。
    if use_tt and transposition_table is not None:
        entry = transposition_table.get(zobrist_key)
        if entry is not None and entry.depth >= depth:
            if entry.flag == "EXACT":
                return entry.value
            if entry.flag == "LOWER" and entry.value > alpha:
                alpha = entry.value
            elif entry.flag == "UPPER" and entry.value < beta:
                beta = entry.value
            if alpha >= beta:
                return entry.value

    # 終止條件：到達深度、或一方將/帥被吃（視為終局）
    if depth <= 0:
        # 主搜尋深度用完：改走「靜態搜尋」避免地平線效應。
        # depth_q 控制靜態搜尋最多再往下看幾層「連續吃子」。
        # 稍微加大 depth_q 可以讓交換序列看得更完整，戰術更穩健（但也會變慢）。
        depth_q = 8
        return quiescence_search(alpha, beta, depth_q)
    if find_king_pos(pieces, "black") is None or find_king_pos(pieces, "red") is None:
        return evaluate_position(pieces, ai_side, get_valid_moves_func, kings_facing_func)

    side_to_play = ai_side if maximizing else ("red" if ai_side == "black" else "black")

    alpha_orig, beta_orig = alpha, beta
    if maximizing:
        value = -10**18
        # 走法排序：先展開「更可能好的走法」（尤其是高價值吃子），alpha 變緊 → 更容易剪枝
        for mv in generate_all_moves(side_to_play, pieces, get_valid_moves_func, history_table=history_table):
            if budget is not None and budget.expired():
                break
            assert hasher is not None
            # 是否吃子（History Heuristic 只更新「非吃子」）
            _src, _dst = mv
            is_capture = (_dst in pieces and pieces[_dst][0] != side_to_play)
            captured, child_key = make_move(pieces, mv, zobrist_key=zobrist_key, hasher=hasher)
            # 將軍延伸：走完後若對手被將軍，多搜一層
            opp = "red" if side_to_play == "black" else "black"
            gives_check = is_in_check(pieces, opp, get_valid_moves_func)
            child_depth = _child_search_depth(depth, gives_check)
            child_score = minimax(
                pieces,
                child_depth,
                False,
                ai_side,
                alpha,
                beta,
                get_valid_moves_func,
                kings_facing_func,
                transposition_table,
                hasher,
                child_key,
                history_table,
                use_tt,
                budget,
            )
            zobrist_key = unmake_move(
                pieces,
                mv,
                captured=captured,
                zobrist_key=child_key,
                hasher=hasher,
            )
            value = max(value, child_score)
            alpha = max(alpha, value)
            if alpha >= beta:
                # ----------------------------
                # History Heuristic（歷史啟發表）更新規則
                # ----------------------------
                # 依你的需求：
                # - 在 alpha-beta 搜尋中，若某「非吃子」走法引發 Beta 剪枝（score >= beta），
                #   則 history_table[from][to] += 2^depth（深度越深，權重越大）。
                #
                # 直覺：
                # - 能在較深層造成剪枝，代表這步在對手回應下仍保持強勢，
                #   是「更可靠」的好棋，因此給更大的權重。
                if (not is_capture) and (child_score >= beta) and history_table is not None:
                    def _idx(p: Pos) -> int:
                        c, r = p
                        return r * 9 + c

                    f, t = mv
                    history_table[_idx(f)][_idx(t)] += 1 << max(0, depth)  # 2^depth
                break  # Beta 剪枝：MIN 已有更好上界，MAX 再搜也不會改變選擇
        # TT 回填
        if use_tt and transposition_table is not None:
            flag = "EXACT"
            if value <= alpha_orig:
                flag = "UPPER"
            elif value >= beta_orig:
                flag = "LOWER"
            transposition_table[zobrist_key] = TTEntry(depth=depth, value=value, flag=flag)
        return value

    # minimizing
    value = 10**18
    # 走法排序：同樣先展開高價值吃子，beta 變緊 → 更容易剪枝
    for mv in generate_all_moves(side_to_play, pieces, get_valid_moves_func, history_table=history_table):
        if budget is not None and budget.expired():
            break
        assert hasher is not None
        captured, child_key = make_move(pieces, mv, zobrist_key=zobrist_key, hasher=hasher)
        opp = "red" if side_to_play == "black" else "black"
        gives_check = is_in_check(pieces, opp, get_valid_moves_func)
        child_depth = _child_search_depth(depth, gives_check)
        child_score = minimax(
            pieces,
            child_depth,
            True,
            ai_side,
            alpha,
            beta,
            get_valid_moves_func,
            kings_facing_func,
            transposition_table,
            hasher,
            child_key,
            history_table,
            use_tt,
            budget,
        )
        zobrist_key = unmake_move(
            pieces,
            mv,
            captured=captured,
            zobrist_key=child_key,
            hasher=hasher,
        )
        value = min(value, child_score)
        beta = min(beta, value)
        if alpha >= beta:
            break  # Alpha 剪枝：MAX 已有更好下界，MIN 再搜也不會改變選擇
    # TT 回填
    if use_tt and transposition_table is not None:
        flag = "EXACT"
        if value <= alpha_orig:
            flag = "UPPER"
        elif value >= beta_orig:
            flag = "LOWER"
        transposition_table[zobrist_key] = TTEntry(depth=depth, value=value, flag=flag)
    return value

