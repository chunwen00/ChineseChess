from __future__ import annotations

import time
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
    depth: int = 2  # 預設搜尋深度 2 層（較快，適合即時對戰）
    use_tt: bool = True  # 是否啟用簡易置換表（快取）以加速
    time_limit_sec: float = 1.5  # 單步思考時間上限（秒）；逾時回傳目前已算出的最佳走法


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
    - 只吃子價值做排序（O(1)），避免在排序時反覆呼叫 get_valid_moves 造成極慢/卡死
    - 先吃子 → Alpha-Beta 更容易早早找到好界限而剪枝
    """
    _src, dst = mv
    captured = pieces.get(dst)
    if captured is not None and captured[0] != side_to_play:
        cap_kind = normalize_kind(captured[1])
        return 10_000 + BASE_VALUE.get(cap_kind, 0)
    return 0


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
    - 位置分：
      - 過河卒（兵）加分
      - 將帥受威脅（被將軍）扣分
    """
    score = 0

    # ----------------------------
    # 1) 基礎分 + 過河卒加分
    # ----------------------------
    for (col, row), (side, name) in pieces.items():
        kind = normalize_kind(name)
        base = BASE_VALUE.get(kind, 0)

        # 過河卒/兵加分：黑卒 row>=5、紅兵 row<=4
        pawn_bonus = 0
        if kind == "卒":
            crossed = (row >= 5) if side == "black" else (row <= 4)
            if crossed:
                pawn_bonus = 5  # 過河加分（可依需要調整）

        value = base + pawn_bonus
        score += value if side == ai_side else -value

    # ----------------------------
    # 2) 將帥受威脅扣分（被將軍）
    # ----------------------------
    # 檢查 ai_side 的將帥是否被對手威脅；若是，扣分
    if is_in_check(pieces, ai_side, get_valid_moves_func):
        score -= 80  # 將帥受威脅扣分（可依需要調整）
    # 檢查對手將帥是否被威脅；若是，加分
    opp = "red" if ai_side == "black" else "black"
    if is_in_check(pieces, opp, get_valid_moves_func):
        score += 80

    # ----------------------------
    # 3) 將帥對面：視為嚴重非法（大幅扣分/加分）
    # ----------------------------
    # 正常走子已避免對面，但在搜尋過程仍可能因為外部函式差異而出現，
    # 這裡保守處理：如果對面，對當前盤面給極端懲罰。
    if kings_facing_func(pieces):
        # 若出現對面，視為對「剛走子的一方」不利，但我們不易判斷剛走子方，
        # 所以採用中性但極端：直接把評估壓到很差（搜尋會自然避開）。
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


def generate_all_moves(side: str, pieces: dict[Pos, Piece], get_valid_moves_func) -> list[Move]:
    """生成 side 的所有合法走法（from->to）。"""
    all_moves: list[Move] = []
    for pos, pc in pieces.items():
        if pc[0] != side:
            continue
        for dst in get_valid_moves_func(pc, pos, pieces):
            all_moves.append((pos, dst))
    # 走法排序（非常重要）：提升 Alpha-Beta 剪枝效果，讓 AI 更快也更強
    all_moves.sort(key=lambda mv: move_order_score(pieces, mv, side), reverse=True)
    return all_moves


def choose_best_move(
    pieces: dict[Pos, Piece],
    ai_side: str,
    get_valid_moves_func,
    kings_facing_func,
    config: AIConfig | None = None,
) -> Move | None:
    """
    用 Minimax + Alpha-Beta 剪枝選出 ai_side 最佳一步。

    Alpha-Beta 剪枝如何減少運算量（中文說明）：
    - 在 Minimax 中，MAX 節點要找「子節點中最大的分數」，MIN 節點要找「最小的分數」。
    - Alpha 表示「目前 MAX 已知的最佳(最大)下界」，Beta 表示「目前 MIN 已知的最佳(最小)上界」。
    - 當在搜尋某分支時發現 alpha >= beta，代表：
      - MAX 已經有一條路保證至少 alpha 分；
      - 但 MIN 在當前分支已能讓結果最多只有 beta 分；
      - 如果 alpha >= beta，這個分支不可能讓雙方選擇改變最終決策，
        因此可以「直接停止」繼續展開子節點（剪枝），大幅減少需要評估的局面數量。
    """
    if config is None:
        config = AIConfig()

    # 若棋局已結束（將/帥不存在），就不需要走
    if find_king_pos(pieces, "black") is None or find_king_pos(pieces, "red") is None:
        return None

    best_move: Move | None = None
    best_score = -10**18
    tt: dict[tuple[Any, ...], int] = {}  # 置換表：快取 (局面key, depth, maximizing) -> 分數
    budget = SearchBudget.from_limit(config.time_limit_sec)  # 建立本步時間預算

    root_moves = generate_all_moves(ai_side, pieces, get_valid_moves_func)
    if not root_moves:
        return None

    # 根節點：AI 是 MAX 端（每評估完一個根走法就檢查是否逾時）
    for mv in root_moves:
        if budget.expired():  # 時間到：不再展開新分支，直接回傳目前已知的最佳走法
            break
        child = apply_move(pieces, mv)
        s = minimax(
            pieces=child,
            depth=config.depth - 1,
            maximizing=False,
            ai_side=ai_side,
            alpha=-10**18,
            beta=10**18,
            get_valid_moves_func=get_valid_moves_func,
            kings_facing_func=kings_facing_func,
            tt=tt,
            use_tt=config.use_tt,
            budget=budget,
        )
        if s > best_score:
            best_score = s
            best_move = mv

    # 若時間太短來不及算任何分數，至少走第一步合法棋（避免 None 卡住）
    if best_move is None:
        best_move = root_moves[0]
    return best_move


def minimax(
    pieces: dict[Pos, Piece],
    depth: int,
    maximizing: bool,
    ai_side: str,
    alpha: int,
    beta: int,
    get_valid_moves_func,
    kings_facing_func,
    tt: dict[tuple[Any, ...], int] | None = None,
    use_tt: bool = True,
    budget: SearchBudget | None = None,
) -> int:
    """Minimax 主遞迴（含 Alpha-Beta 剪枝 + 可選時間上限）。"""
    # 時間上限：逾時就用當前局面評估分數當作截斷值（讓搜尋能盡快返回）
    if budget is not None and budget.expired():
        return evaluate_position(pieces, ai_side, get_valid_moves_func, kings_facing_func)

    # 終止條件：到達深度、或一方將/帥被吃（視為終局）
    if depth <= 0:
        return evaluate_position(pieces, ai_side, get_valid_moves_func, kings_facing_func)
    if find_king_pos(pieces, "black") is None or find_king_pos(pieces, "red") is None:
        return evaluate_position(pieces, ai_side, get_valid_moves_func, kings_facing_func)

    # 置換表（TT）快取：同一局面在同深度/輪到誰時結果相同，可直接取用避免重算
    if use_tt and tt is not None:
        k = board_key(pieces) + (depth, maximizing, ai_side)
        cached = tt.get(k)
        if cached is not None:
            return cached

    side_to_play = ai_side if maximizing else ("red" if ai_side == "black" else "black")

    if maximizing:
        value = -10**18
        for mv in generate_all_moves(side_to_play, pieces, get_valid_moves_func):
            if budget is not None and budget.expired():
                break
            child = apply_move(pieces, mv)
            value = max(
                value,
                minimax(child, depth - 1, False, ai_side, alpha, beta, get_valid_moves_func, kings_facing_func, tt, use_tt, budget),
            )
            alpha = max(alpha, value)
            if alpha >= beta:
                break  # Beta 剪枝：MIN 已有更好上界，MAX 再搜也不會改變選擇
        if use_tt and tt is not None:
            tt[k] = value
        return value

    # minimizing
    value = 10**18
    for mv in generate_all_moves(side_to_play, pieces, get_valid_moves_func):
        if budget is not None and budget.expired():
            break
        child = apply_move(pieces, mv)
        value = min(
            value,
            minimax(child, depth - 1, True, ai_side, alpha, beta, get_valid_moves_func, kings_facing_func, tt, use_tt, budget),
        )
        beta = min(beta, value)
        if alpha >= beta:
            break  # Alpha 剪枝：MAX 已有更好下界，MIN 再搜也不會改變選擇
    if use_tt and tt is not None:
        tt[k] = value
    return value

