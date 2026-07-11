import os  # 用於判斷 Windows 字型檔是否存在（字型 fallback 用）
import sys  # 用於程式結束時呼叫 sys.exit
import threading  # 讓 AI 在背景執行，避免畫面卡住
import pygame  # 遊戲視窗/繪圖/事件迴圈（pygame）

from ai import AIConfig, choose_best_move  # AI：Minimax + Alpha-Beta + 評估函數

"""
中國象棋（第一步：畫出棋盤 + 初始棋子）

需求重點：
1) 800x900 視窗
2) 繪製棋盤（含九宮格、楚河漢界）
3) 定義初始佈局（紅黑雙方：車馬炮象士將卒）
4) 棋子以「圓圈 + 文字」表示，不載入外部圖片
5) 以詳細中文註解說明：棋盤座標(列/行)如何映射到像素

座標系統約定（非常重要）：
- 中國象棋棋盤有 9 列 x 10 行 的「落子點」（不是格子中心）
  - 列 col：0..8（從左到右）
  - 行 row：0..9（從上到下）
- 我們採用「黑方在上，紅方在下」的常見螢幕呈現：
  - 黑方主將（將）在上方 row=0..2 的九宮格
  - 紅方主帥（帥）在下方 row=7..9 的九宮格

像素座標系統（pygame）：
- 螢幕左上角是 (0,0)
- x 向右遞增，y 向下遞增
"""


# ----------------------------
# 視窗與棋盤幾何參數
# ----------------------------
WINDOW_W, WINDOW_H = 800, 900  # 視窗寬高（像素）
STATUS_BAR_H = 48  # 頂部狀態列高度（容納按鈕與狀態文字）

# 棋盤落子點間距（像素）。這個值越大，棋盤越大。
# 棋盤的線段跨度為：
# - 水平：8 個間距（因為 9 個落子點形成 8 段）
# - 垂直：9 個間距（因為 10 個落子點形成 9 段）
CELL = 80  # 相鄰落子點的像素距離（格點間距）

BOARD_W = 8 * CELL  # 棋盤線的水平跨度（9 列落子點 → 8 段）
BOARD_H = 9 * CELL  # 棋盤線的垂直跨度（10 行落子點 → 9 段）

# 讓棋盤在 800x900 中置中，留出邊界空間
MARGIN_X = (WINDOW_W - BOARD_W) // 2  # 棋盤左邊界（讓棋盤水平置中）
MARGIN_Y = (WINDOW_H - BOARD_H) // 2  # 棋盤上邊界（讓棋盤垂直置中）

# 目前盤面（給 get_valid_moves 的預設參考；實際上 main 迴圈也會同步更新）
CURRENT_PIECES: dict[tuple[int, int], tuple[str, str]] = {}  # {(col,row): (side,name)}

# 棋盤「格點(列/行)」映射到螢幕像素的函式
def board_to_screen(col: int, row: int) -> tuple[int, int]:
    """
    將棋盤座標 (col, row) 轉成螢幕像素 (x, y)。

    - col=0 對應最左側豎線與落子點
    - col=8 對應最右側豎線與落子點
    - row=0 對應最上方橫線與落子點
    - row=9 對應最下方橫線與落子點

    映射公式：
      x = MARGIN_X + col * CELL
      y = MARGIN_Y + row * CELL
    """
    x = MARGIN_X + col * CELL  # col 每 +1，就往右增加一個 CELL 像素
    y = MARGIN_Y + row * CELL  # row 每 +1，就往下增加一個 CELL 像素
    return x, y  # 回傳該落子點在螢幕上的像素座標


def screen_to_board(x: int, y: int) -> tuple[int, int] | None:
    """
    將滑鼠像素座標 (x,y) 反推為棋盤座標 (col,row)。

    核心想法：
    - 落子點是規則網格：每個點間距為 CELL
    - 所以先把 (x,y) 平移到以棋盤左上角為原點，再除以 CELL 得到「接近的 col,row」
    - 使用 round 取最近的落子點，並要求滑鼠必須在該落子點附近（避免點到空白也被吸附）
    """
    local_x = x - MARGIN_X  # 將像素 x 轉成相對棋盤左邊界的座標
    local_y = y - MARGIN_Y  # 將像素 y 轉成相對棋盤上邊界的座標
    col = int(round(local_x / CELL))  # 四捨五入到最近的棋盤列（0..8）
    row = int(round(local_y / CELL))  # 四捨五入到最近的棋盤行（0..9）

    if not (0 <= col <= 8 and 0 <= row <= 9):  # 若超出棋盤範圍就回傳 None
        return None  # 表示此次點擊不在棋盤上

    # 檢查是否真的點在該落子點附近（距離太遠就視為無效點擊）            
    px, py = board_to_screen(col, row)  # 取得該落子點的像素座標
    dist2 = (x - px) * (x - px) + (y - py) * (y - py)  # 計算與落子點的距離平方
    snap_radius = 36  # 允許吸附的半徑（要略大於棋子半徑）
    if dist2 > snap_radius * snap_radius:  # 若離落子點太遠
        return None  # 不吸附，避免誤觸

    return col, row  # 回傳棋盤座標
    


def draw_board(screen: pygame.Surface, font: pygame.font.Font) -> None:
    """繪製棋盤：外框、橫線、豎線（中間楚河漢界斷開）、九宮格斜線、楚河漢界文字。"""
    bg_color = (245, 222, 179)  # 背景色：類似木色（wheat）
    line_color = (60, 40, 20)  # 線條色：深棕色
    screen.fill(bg_color)  # 先把整個畫面填滿背景色

    # 外框（把棋盤線的最大/最小像素座標算出來）
    left, top = board_to_screen(0, 0)  # 棋盤左上角落子點像素
    right, bottom = board_to_screen(8, 9)  # 棋盤右下角落子點像素
    pygame.draw.rect(  # 畫外框矩形（加粗）
        screen,  # 畫在此 surface
        line_color,  # 使用線條顏色
        pygame.Rect(left, top, right - left, bottom - top),  # 外框矩形區域
        width=3,  # 外框線寬
    )  # 外框完成

    # ----------------------------
    # 1) 畫橫線（row=0..9）
    # ----------------------------
    # 注意：象棋中「楚河漢界」在 row=4 與 row=5 之間，通常不畫那一條中線。
    # 也就是說：橫線畫 row=0..4 以及 row=5..9 這些落子點所在的橫線，
    # 但不畫 row=4 與 row=5 之間那條「連接兩側的長橫線」。
    #
    # 在我們用「落子點連線」的畫法中，橫線就是從 col=0 到 col=8 的線段。
    # 由於河界是在「兩排落子點之間」，所以橫線照樣畫 row=4 與 row=5 的線；
    # 真正需要斷開的是「中間的縱線」與「河界文字區域」的視覺空白。
    #
    # 下面我們仍然把 row=0..9 的橫線全部畫出來（這是常見棋盤畫法）。
    for row in range(10):  # 逐行畫 10 條橫線（row=0..9 的落子點連線）
        x1, y = board_to_screen(0, row)  # 該橫線左端點（col=0）像素
        x2, _ = board_to_screen(8, row)  # 該橫線右端點（col=8）像素（y 相同）
        pygame.draw.line(screen, line_color, (x1, y), (x2, y), width=2)  # 畫橫線

    # ----------------------------
    # 2) 畫豎線（col=0..8），中間河界斷開
    # ----------------------------
    # 象棋棋盤的豎線在河界（row=4 與 row=5 之間）是斷開的：
    # - 左右兩邊框 col=0, col=8 是完整連到底
    # - 中間豎線 col=1..7 需要在河界處留出一段空白
    for col in range(9):  # 逐列畫 9 條豎線（col=0..8）
        x, y_top = board_to_screen(col, 0)  # 豎線頂端（row=0）像素
        _, y_river_top = board_to_screen(col, 4)  # 河界上方端點（row=4）像素
        _, y_river_bottom = board_to_screen(col, 5)  # 河界下方端點（row=5）像素
        _, y_bottom = board_to_screen(col, 9)  # 豎線底端（row=9）像素

        if col == 0 or col == 8:  # 最左/最右邊框豎線不斷開（整條連到底）
            pygame.draw.line(screen, line_color, (x, y_top), (x, y_bottom), width=2)  # 畫整條豎線
        else:  # 中間豎線在楚河漢界處需要斷開
            pygame.draw.line(screen, line_color, (x, y_top), (x, y_river_top), width=2)  # 上半段（row 0->4）
            pygame.draw.line(screen, line_color, (x, y_river_bottom), (x, y_bottom), width=2)  # 下半段（row 5->9）

    # ----------------------------
    # 3) 九宮格（兩個 3x3 宮）畫斜線
    # ----------------------------
    # 黑方九宮格：col=3..5, row=0..2
    # 斜線： (3,0)->(5,2) 以及 (5,0)->(3,2)
    a1 = board_to_screen(3, 0)  # 黑方九宮格左上角（col=3,row=0）像素
    a2 = board_to_screen(5, 2)  # 黑方九宮格右下角（col=5,row=2）像素
    b1 = board_to_screen(5, 0)  # 黑方九宮格右上角（col=5,row=0）像素
    b2 = board_to_screen(3, 2)  # 黑方九宮格左下角（col=3,row=2）像素
    pygame.draw.line(screen, line_color, a1, a2, width=2)  # 畫斜線：左上→右下
    pygame.draw.line(screen, line_color, b1, b2, width=2)  # 畫斜線：右上→左下

    # 紅方九宮格：col=3..5, row=7..9
    c1 = board_to_screen(3, 7)  # 紅方九宮格左上角（col=3,row=7）像素
    c2 = board_to_screen(5, 9)  # 紅方九宮格右下角（col=5,row=9）像素
    d1 = board_to_screen(5, 7)  # 紅方九宮格右上角（col=5,row=7）像素
    d2 = board_to_screen(3, 9)  # 紅方九宮格左下角（col=3,row=9）像素
    pygame.draw.line(screen, line_color, c1, c2, width=2)  # 畫斜線：左上→右下
    pygame.draw.line(screen, line_color, d1, d2, width=2)  # 畫斜線：右上→左下

    # ----------------------------
    # 4) 楚河漢界文字（放在河界中間）
    # ----------------------------
    # 河界位於 row=4 與 row=5 之間的空白區域中心
    river_y = (board_to_screen(0, 4)[1] + board_to_screen(0, 5)[1]) // 2  # 河界中線 y（介於 row=4 與 row=5）
    left_center_x = (board_to_screen(1, 0)[0] + board_to_screen(3, 0)[0]) // 2  # 左側「楚河」文字中心 x
    right_center_x = (board_to_screen(5, 0)[0] + board_to_screen(7, 0)[0]) // 2  # 右側「漢界」文字中心 x

    chu = font.render("楚河", True, line_color)  # 把「楚河」渲染成文字 surface
    han = font.render("漢界", True, line_color)  # 把「漢界」渲染成文字 surface
    screen.blit(chu, chu.get_rect(center=(left_center_x, river_y)))  # 將「楚河」貼到左半邊河界中央
    screen.blit(han, han.get_rect(center=(right_center_x, river_y)))  # 將「漢界」貼到右半邊河界中央


def get_initial_pieces() -> dict[tuple[int, int], tuple[str, str]]:
    """
    回傳初始棋子佈局。

    回傳格式：
      {(col,row): (side, piece)}
    - side: "red" 或 "black"
    - piece: 使用中文棋子名稱（紅方常用：車馬相仕帥炮兵；黑方：車馬象士將炮卒）
    """
    pieces: dict[tuple[int, int], tuple[str, str]] = {}  # 用字典保存所有棋子（key=座標，value=陣營+名稱）

    # 黑方（上）
    # 車馬象士將士象馬車
    back_black = ["車", "馬", "象", "士", "將", "士", "象", "馬", "車"]  # 黑方底線（最上 row=0）九子
    for col, name in enumerate(back_black):  # col 由 0..8 對應每個位置
        pieces[(col, 0)] = ("black", name)  # 放到 row=0 的對應 col
    # 炮
    pieces[(1, 2)] = ("black", "炮")  # 黑方左炮（col=1,row=2）
    pieces[(7, 2)] = ("black", "炮")  # 黑方右炮（col=7,row=2）
    # 卒
    for col in range(0, 9, 2):  # 黑方五卒在奇數列間隔擺放：0,2,4,6,8
        pieces[(col, 3)] = ("black", "卒")  # 黑卒所在 row=3

    # 紅方（下）
    # 車馬相仕帥仕相馬車
    back_red = ["車", "馬", "相", "仕", "帥", "仕", "相", "馬", "車"]  # 紅方底線（最下 row=9）九子
    for col, name in enumerate(back_red):  # col 由 0..8 對應每個位置
        pieces[(col, 9)] = ("red", name)  # 放到 row=9 的對應 col
    # 炮
    pieces[(1, 7)] = ("red", "炮")  # 紅方左炮（col=1,row=7）
    pieces[(7, 7)] = ("red", "炮")  # 紅方右炮（col=7,row=7）
    # 兵
    for col in range(0, 9, 2):  # 紅方五兵同樣間隔擺放：0,2,4,6,8
        pieces[(col, 6)] = ("red", "兵")  # 紅兵所在 row=6

    return pieces  # 回傳初始棋子字典


def draw_pieces(
    screen: pygame.Surface,
    pieces: dict[tuple[int, int], tuple[str, str]],
    piece_font: pygame.font.Font,
) -> None:
    """用圓圈 + 文字畫棋子（不載入外部圖片）。"""
    # 棋子外觀
    outline = (60, 40, 20)  # 棋子外框顏色（深棕）
    fill = (250, 245, 235)  # 棋子填滿顏色（偏白）
    red_color = (180, 30, 30)  # 紅方文字顏色（紅）
    black_color = (20, 20, 20)  # 黑方文字顏色（黑）
    radius = 32  # 棋子半徑（要小於 CELL/2 才不會壓到棋盤線）

    for (col, row), (side, name) in pieces.items():  # 逐顆棋子遍歷
        x, y = board_to_screen(col, row)  # 將棋盤座標轉為像素座標（落子點位置）

        # 圓形棋子
        pygame.draw.circle(screen, fill, (x, y), radius)  # 畫棋子底色圓
        pygame.draw.circle(screen, outline, (x, y), radius, width=3)  # 畫棋子外框圓

        # 文字（紅黑不同顏色）
        text_color = red_color if side == "red" else black_color  # 根據陣營決定文字顏色
        text = piece_font.render(name, True, text_color)  # 把棋子名稱渲染成文字 surface
        screen.blit(text, text.get_rect(center=(x, y)))  # 置中貼到棋子圓心上


def draw_single_piece_at_pixel(
    screen: pygame.Surface,
    piece: tuple[str, str],
    px: int,
    py: int,
    piece_font: pygame.font.Font,
) -> None:
    """將單顆棋子畫在「任意像素位置」(用於拖曳時跟隨滑鼠)。"""
    side, name = piece  # 拆出陣營與棋子名稱
    outline = (60, 40, 20)  # 棋子外框顏色（深棕）
    fill = (250, 245, 235)  # 棋子填滿顏色（偏白）
    red_color = (180, 30, 30)  # 紅方文字顏色（紅）
    black_color = (20, 20, 20)  # 黑方文字顏色（黑）
    radius = 32  # 棋子半徑

    pygame.draw.circle(screen, fill, (px, py), radius)  # 畫棋子底色圓（跟著滑鼠）
    pygame.draw.circle(screen, outline, (px, py), radius, width=3)  # 畫棋子外框圓
    text_color = red_color if side == "red" else black_color  # 根據陣營決定文字顏色
    text = piece_font.render(name, True, text_color)  # 把棋子名稱渲染成文字 surface
    screen.blit(text, text.get_rect(center=(px, py)))  # 置中貼到棋子圓心上


def draw_move_hints(screen: pygame.Surface, moves: set[tuple[int, int]]) -> None:
    """用小圓點提示「可走位置」(不包含吃子特效，純提示)。"""
    hint_color = (20, 120, 200)  # 提示點顏色（藍）
    for col, row in moves:  # 逐個落點提示
        x, y = board_to_screen(col, row)  # 取得該落點像素座標
        pygame.draw.circle(screen, hint_color, (x, y), 10)  # 畫小圓點提示


def is_red_piece(name: str) -> bool:
    """用棋子文字判斷是否屬於紅方（紅方有：相仕帥兵）。"""
    return name in {"相", "仕", "帥", "兵"}  # 其餘通用字（車馬炮）依 side 判斷更可靠


def piece_side_at(pieces: dict[tuple[int, int], tuple[str, str]], pos: tuple[int, int]) -> str | None:
    """回傳某格的陣營（'red'/'black'），若該格無棋子則回傳 None。"""
    v = pieces.get(pos)  # 讀取該格內容
    return None if v is None else v[0]  # v[0] 是 side


def find_king_positions(pieces: dict[tuple[int, int], tuple[str, str]]) -> tuple[tuple[int, int] | None, tuple[int, int] | None]:
    """找出 (黑將位置, 紅帥位置)。"""
    black_king = None  # 黑將座標
    red_king = None  # 紅帥座標
    for (col, row), (side, name) in pieces.items():  # 掃描所有棋子
        if side == "black" and name == "將":  # 黑將
            black_king = (col, row)  # 記錄黑將位置
        if side == "red" and name == "帥":  # 紅帥
            red_king = (col, row)  # 記錄紅帥位置
    return black_king, red_king  # 回傳兩者


def kings_facing(pieces: dict[tuple[int, int], tuple[str, str]]) -> bool:
    """
    判斷是否出現「將帥對面」的非法局面：
    - 黑將與紅帥在同一列(col 相同)
    - 且兩者之間沒有任何棋子阻擋
    """
    black_king, red_king = find_king_positions(pieces)  # 找將帥位置
    if black_king is None or red_king is None:  # 若任一缺失（被吃掉）
        return False  # 先不視為對面（遊戲完整性後續可再加）

    bk_col, bk_row = black_king  # 黑將 col,row
    rk_col, rk_row = red_king  # 紅帥 col,row
    if bk_col != rk_col:  # 不同列就不可能對面
        return False  # 直接回傳

    # 在同一列：檢查 row 之間是否有其他棋子
    r1, r2 = sorted([bk_row, rk_row])  # 找出上下 row 範圍
    for row in range(r1 + 1, r2):  # 掃描兩者之間的每一行
        if (bk_col, row) in pieces:  # 中間有任一棋子阻擋
            return False  # 不是對面
    return True  # 中間完全無子 → 將帥對面（非法）


def opponent_side(side: str) -> str:
    """回傳對手陣營。"""
    return "black" if side == "red" else "red"


def find_king_pos(pieces: dict[tuple[int, int], tuple[str, str]], side: str) -> tuple[int, int] | None:
    """找出指定陣營將/帥所在格；若已被吃則回傳 None。"""
    for pos, (s, name) in pieces.items():
        if s != side:
            continue
        if (side == "black" and name == "將") or (side == "red" and name == "帥"):
            return pos
    return None


def is_in_check(pieces: dict[tuple[int, int], tuple[str, str]], side: str) -> bool:
    """
    判斷 side 是否處於「被將軍」狀態。

    判斷思路（逐步對應程式碼）：
    1) 先找到 side 的將/帥在哪一格（king_pos）
       - 若找不到 → 代表將/帥已被吃，視為被將軍（局面已結束）
    2) 找出敵方陣營 enemy
    3) 枚舉敵方每一顆棋子 (pos, piece)
    4) 對該敵子計算它在「目前盤面」能攻擊/移動到的落點集合 get_valid_moves(...)
       - 注意：這裡用 filter_self_check=False，避免遞迴過濾造成無限呼叫
    5) 若 king_pos 出現在敵方任一枚子的攻擊落點中
       → 代表敵方可「下一步直接吃到將/帥」→ side 被將軍
    """
    king_pos = find_king_pos(pieces, side)  # 1) 找將/帥
    if king_pos is None:  # 將/帥不存在
        return True  # 視為被將軍（通常代表已輸）

    enemy = opponent_side(side)  # 2) 敵方陣營
    for pos, piece in pieces.items():  # 3) 枚舉敵子
        if piece[0] != enemy:  # 只檢查敵方棋子
            continue
        attack_squares = get_valid_moves(  # 4) 敵子攻擊/可走落點
            piece,
            pos,
            pieces,
            filter_self_check=False,  # 判斷威脅時不做「送將過濾」
        )
        if king_pos in attack_squares:  # 5) 敵子能打到將/帥格
            return True  # 被將軍
    return False  # 沒有任何敵子能直接攻擊到將/帥


def get_all_legal_moves_for_side(
    pieces: dict[tuple[int, int], tuple[str, str]],
    side: str,
) -> list[tuple[tuple[int, int], tuple[int, int]]]:
    """取得某方所有「真正合法」的 (起點, 終點) 走法（含不可送將過濾）。"""
    all_moves: list[tuple[tuple[int, int], tuple[int, int]]] = []
    for pos, piece in pieces.items():
        if piece[0] != side:
            continue
        for dst in get_valid_moves(piece, pos, pieces, filter_self_check=True):
            all_moves.append((pos, dst))
    return all_moves


def side_label(side: str) -> str:
    """陣營顯示名稱。"""
    return "紅方" if side == "red" else "黑方"


def evaluate_game_after_move(
    pieces: dict[tuple[int, int], tuple[str, str]],
    mover_side: str,
) -> tuple[str | None, str]:
    """
    在 mover_side 走完一步後，判定是否結束以及狀態文字。

    回傳：(winner_side 或 None, status_text)
    - 將/帥被吃 → mover 贏
    - 對手無任何合法走法 → mover 贏（將死或困毙）
    - 否則若對手被將軍 → 狀態提示「將軍」
    """
    opponent = opponent_side(mover_side)
    if find_king_pos(pieces, opponent) is None:
        return mover_side, f"{side_label(mover_side)}獲勝！（將/帥被吃）"

    legal = get_all_legal_moves_for_side(pieces, opponent)
    if not legal:
        if is_in_check(pieces, opponent):
            return mover_side, f"{side_label(mover_side)}獲勝！（將死）"
        return mover_side, f"{side_label(mover_side)}獲勝！（困毙：對方無路可走）"

    if is_in_check(pieces, opponent):
        return None, f"{side_label(opponent)}被將軍！輪到{side_label(opponent)}"
    return None, f"輪到{side_label(opponent)}"


def show_winner_dialog(
    screen: pygame.Surface,
    title_font: pygame.font.Font,
    body_font: pygame.font.Font,
    message: str,
    clock: pygame.time.Clock,
) -> None:
    """弹出提示視窗（pygame 模態 overlay）：宣告贏家，點擊或按鍵關閉。"""
    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return
            if event.type == pygame.KEYDOWN:
                return
            if event.type == pygame.MOUSEBUTTONDOWN:
                return

        overlay = pygame.Surface((WINDOW_W, WINDOW_H), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 170))
        screen.blit(overlay, (0, 0))

        box_w, box_h = 520, 220
        box_x = (WINDOW_W - box_w) // 2
        box_y = (WINDOW_H - box_h) // 2
        pygame.draw.rect(screen, (255, 248, 220), pygame.Rect(box_x, box_y, box_w, box_h), border_radius=12)
        pygame.draw.rect(screen, (120, 80, 40), pygame.Rect(box_x, box_y, box_w, box_h), width=3, border_radius=12)

        title = title_font.render("對局結束", True, (120, 20, 20))
        body = body_font.render(message, True, (40, 40, 40))
        hint = body_font.render("按任意鍵或點擊關閉", True, (80, 80, 80))
        screen.blit(title, title.get_rect(center=(WINDOW_W // 2, box_y + 50)))
        screen.blit(body, body.get_rect(center=(WINDOW_W // 2, box_y + 110)))
        screen.blit(hint, hint.get_rect(center=(WINDOW_W // 2, box_y + 170)))

        pygame.display.flip()
        clock.tick(30)


def push_history(
    history_stack: list[dict],
    pieces: dict[tuple[int, int], tuple[str, str]],
    turn: str,
    status_text: str,
) -> None:
    """將目前局面推入 history_stack（供悔棋使用）。"""
    history_stack.append(
        {
            "pieces": dict(pieces),
            "turn": turn,
            "status_text": status_text,
        }
    )


def restore_from_history(entry: dict) -> tuple[dict[tuple[int, int], tuple[str, str]], str, str]:
    """從 history 條目還原 (pieces, turn, status_text)。"""
    return dict(entry["pieces"]), entry["turn"], entry["status_text"]

    """判斷 (col,row) 是否在該陣營九宮格內。"""
    if not (3 <= col <= 5):  # 九宮格列固定是 3..5
        return False  # 不在九宮格
    if side == "black":  # 黑方九宮格在上方
        return 0 <= row <= 2  # row 0..2
    return 7 <= row <= 9  # 紅方九宮格在下方 row 7..9


def add_if_empty_or_enemy(
    moves: set[tuple[int, int]],
    pieces: dict[tuple[int, int], tuple[str, str]],
    side: str,
    col: int,
    row: int,
) -> None:
    """若目標格在棋盤內，且為空或敵子，則加入 moves。"""
    if not (0 <= col <= 8 and 0 <= row <= 9):  # 邊界檢查
        return  # 超出棋盤
    target = (col, row)  # 目標座標
    if target not in pieces:  # 空格
        moves.add(target)  # 可走
        return  # 結束
    if pieces[target][0] != side:  # 有棋子但陣營不同（敵子）
        moves.add(target)  # 可吃（也算合法落點）


def get_valid_moves(
    piece: tuple[str, str],
    position: tuple[int, int],
    pieces: dict[tuple[int, int], tuple[str, str]] | None = None,
    filter_self_check: bool = True,
) -> set[tuple[int, int]]:
    """
    計算某棋子在 position 的合法走法集合。

    piece: (side, name)
      - side: "red" / "black"
      - name: "車馬炮象士將卒" 或紅方的 "相仕帥兵"

    本函式重點規則（依你要求必須嚴格遵守）：
    - 馬：走「日」字，但若「拐馬腳」位置有棋子則該方向不可走
    - 象/相：走「田」字（對角兩格），且「象眼」被擋不可走；另外不可過河
    - 炮：平移如車；不吃子時路徑需全空；吃子時必須「翻山」(中間恰好隔 1 子)
    - 將/帥：九宮格內上下左右一步，且不得形成「將帥對面」
    - filter_self_check=True 時：再走一步後不可讓己方將/帥仍被攻擊（不可送將）
    """
    if pieces is None:  # 若沒傳入 pieces，就使用全域 CURRENT_PIECES
        pieces = CURRENT_PIECES  # 使用目前盤面

    side, name = piece  # 拆出陣營與棋子名稱
    col, row = position  # 拆出目前位置
    moves: set[tuple[int, int]] = set()  # 收集所有合法落點

    # 把紅方特有名稱轉成「統一棋種」判斷用的代碼
    # 例如：紅方「相」與黑方「象」同規則；紅方「帥」與黑方「將」同規則。
    if name == "相":  # 紅相
        kind = "象"  # 視為象類
    elif name == "仕":  # 紅仕
        kind = "士"  # 視為士類
    elif name == "帥":  # 紅帥
        kind = "將"  # 視為將類
    elif name == "兵":  # 紅兵
        kind = "卒"  # 視為卒類（用 side 分辨前進方向）
    else:
        kind = name  # 車馬炮象士將卒原樣

    # ----------------------------
    # 車：直線走，遇子停止；敵子可吃，己子不可穿過
    # ----------------------------
    if kind == "車":
        for dc, dr in [(1, 0), (-1, 0), (0, 1), (0, -1)]:  # 四個方向
            c, r = col + dc, row + dr  # 從相鄰格開始掃描
            while 0 <= c <= 8 and 0 <= r <= 9:  # 在棋盤內才繼續
                if (c, r) not in pieces:  # 空格
                    moves.add((c, r))  # 可走
                else:  # 遇到棋子就停止（但可吃敵子）
                    if pieces[(c, r)][0] != side:  # 敵子
                        moves.add((c, r))  # 可吃
                    break  # 不可再往前
                c += dc  # 繼續往該方向前進
                r += dr  # 繼續往該方向前進

    # ----------------------------
    # 馬：走日字 + 拐馬腳
    # ----------------------------
    elif kind == "馬":
        # 馬的 8 個目標位移，以及對應的「馬腳」阻擋格：
        # 例：往右上（+2,-1）時，必須先能往右走一步（+1,0），該格就是馬腳
        horse_steps = [
            ((+2, -1), (+1, 0)),
            ((+2, +1), (+1, 0)),
            ((-2, -1), (-1, 0)),
            ((-2, +1), (-1, 0)),
            ((+1, -2), (0, -1)),
            ((-1, -2), (0, -1)),
            ((+1, +2), (0, +1)),
            ((-1, +2), (0, +1)),
        ]
        for (dc, dr), (leg_dc, leg_dr) in horse_steps:  # 逐方向檢查
            leg = (col + leg_dc, row + leg_dr)  # 馬腳位置（必須為空）
            if not (0 <= leg[0] <= 8 and 0 <= leg[1] <= 9):  # 馬腳若出界
                continue  # 直接跳過該方向
            if leg in pieces:  # 若馬腳被棋子佔據 → 拐馬腳，不能走該方向
                continue  # 該方向無效

            target_col = col + dc  # 目標列
            target_row = row + dr  # 目標行
            add_if_empty_or_enemy(moves, pieces, side, target_col, target_row)  # 空格或敵子則可走/可吃

    # ----------------------------
    # 象/相：田字格 + 象眼 + 不過河
    # ----------------------------
    elif kind == "象":
        # 象走「對角兩格」：(+2,+2), (+2,-2), (-2,+2), (-2,-2)
        # 並且「象眼」是中間那一格（+1,+1）等，若被擋就不能走。
        elephant_steps = [
            (+2, +2),
            (+2, -2),
            (-2, +2),
            (-2, -2),
        ]
        for dc, dr in elephant_steps:  # 逐方向檢查
            eye_col = col + dc // 2  # 象眼列（中間格）
            eye_row = row + dr // 2  # 象眼行（中間格）
            if (eye_col, eye_row) in pieces:  # 象眼被佔據 → 不能走（田字被堵）
                continue  # 該方向不合法

            target_col = col + dc  # 目標列（兩格斜走）
            target_row = row + dr  # 目標行（兩格斜走）

            # 不能過河：
            # - 黑方象只能在上半場（row 0..4）
            # - 紅方相只能在下半場（row 5..9）
            if side == "black" and target_row > 4:  # 黑象跨到河的下方
                continue  # 不合法
            if side == "red" and target_row < 5:  # 紅相跨到河的上方
                continue  # 不合法

            add_if_empty_or_enemy(moves, pieces, side, target_col, target_row)  # 空格或敵子則可走/可吃

    # ----------------------------
    # 士/仕：九宮格內斜走一步
    # ----------------------------
    elif kind == "士":
        for dc, dr in [(1, 1), (1, -1), (-1, 1), (-1, -1)]:  # 四個斜方向
            tc, tr = col + dc, row + dr  # 目標
            if not in_palace(side, tc, tr):  # 必須在九宮格內
                continue  # 不合法
            add_if_empty_or_enemy(moves, pieces, side, tc, tr)  # 空格或敵子則可走/可吃

    # ----------------------------
    # 將/帥：九宮格內直走一步 + 禁止對面
    # ----------------------------
    elif kind == "將":
        for dc, dr in [(1, 0), (-1, 0), (0, 1), (0, -1)]:  # 上下左右一步
            tc, tr = col + dc, row + dr  # 目標
            if not in_palace(side, tc, tr):  # 將帥不可出九宮格
                continue  # 不合法
            add_if_empty_or_enemy(moves, pieces, side, tc, tr)  # 先加入候選

    # ----------------------------
    # 炮：走法如車；吃子需翻山（隔一子）
    # ----------------------------
    elif kind == "炮":
        # 炮的判定要分兩種狀態：
        # - 尚未翻山（尚未跨過任何棋子）：只能走到空格，遇到第一個棋子就停止「走」並進入翻山狀態
        # - 已翻山（已經跨過 1 個棋子）：接下來遇到的第一個棋子若為敵子可吃；不論敵我都停止
        for dc, dr in [(1, 0), (-1, 0), (0, 1), (0, -1)]:  # 四個方向
            c, r = col + dc, row + dr  # 從相鄰格開始掃描
            jumped = False  # 是否已經翻過山（是否已跨過 1 個棋子）
            while 0 <= c <= 8 and 0 <= r <= 9:  # 還在棋盤內就繼續
                if (c, r) not in pieces:  # 目前格子是空
                    if not jumped:  # 未翻山前：空格都可走
                        moves.add((c, r))  # 加入可走落點
                    # 已翻山後：空格不可落子（炮吃子必須落在棋子格），所以不加入
                else:  # 目前格子有棋子
                    if not jumped:  # 第一次遇到棋子：把它當作「山」
                        jumped = True  # 狀態切換為已翻山
                    else:  # 已翻山後再次遇到棋子：這顆是「可吃的目標」或「阻擋」
                        if pieces[(c, r)][0] != side:  # 若是敵子
                            moves.add((c, r))  # 可吃（翻山吃子）
                        break  # 不管敵我，遇到第二顆棋子都必須停止
                c += dc  # 往前掃描
                r += dr  # 往前掃描

    # ----------------------------
    # 卒/兵：前進一步；過河後可左右一步；不能後退
    # ----------------------------
    elif kind == "卒":
        forward = 1 if side == "black" else -1  # 黑方往下（row+1），紅方往上（row-1）
        add_if_empty_or_enemy(moves, pieces, side, col, row + forward)  # 向前一步

        crossed = (row >= 5) if side == "black" else (row <= 4)  # 是否已過河（黑>4、紅<5）
        if crossed:  # 過河後才允許左右
            add_if_empty_or_enemy(moves, pieces, side, col - 1, row)  # 向左一步
            add_if_empty_or_enemy(moves, pieces, side, col + 1, row)  # 向右一步

    # ----------------------------
    # 將帥對面檢查：把會導致「對面」的走法從 moves 中剔除
    # ----------------------------
    legal_moves: set[tuple[int, int]] = set()  # 過濾後的合法集合
    for target in moves:  # 逐一檢查候選走法
        test = dict(pieces)  # 複製一份盤面（淺拷貝足夠）
        test.pop((col, row), None)  # 移除原位置棋子
        test[target] = (side, name)  # 放到目標位置（若有敵子會被覆蓋→等同吃子）
        if kings_facing(test):  # 若形成將帥對面
            continue  # 剔除該走法
        if filter_self_check and is_in_check(test, side):  # 走完後己方仍被將軍 → 送將，不可走
            continue
        legal_moves.add(target)  # 否則保留

    return legal_moves  # 回傳最終合法落點集合


def in_palace(side: str, col: int, row: int) -> bool:
    """判斷 (col,row) 是否在該陣營九宮格內。"""
    if not (3 <= col <= 5):  # 九宮格列固定是 3..5
        return False
    if side == "black":  # 黑方九宮格在上方
        return 0 <= row <= 2
    return 7 <= row <= 9  # 紅方九宮格在下方 row 7..9


def load_cjk_font(size: int, bold: bool = False) -> pygame.font.Font:
    """
    載入「能顯示中文」的字型，並提供可靠的 Windows fallback。

    為什麼需要這個函式？
    - `pygame.font.SysFont("SimHei", ...)` 依賴系統字型註冊名稱，
      在不同 Windows/語系環境可能：
        1) 找不到該名稱（結果退回預設字型，中文就會變方框）
        2) 找到的不是預期字型（筆畫/字形看起來錯誤）
    - 因此我們採用「先試 SysFont 多候選」→「再試直接載入字型檔」的策略。
    """

    # 先定義一組「必須能顯示」的字元，用來避免選到缺字字型而出現方框/亂碼。
    # 這些字涵蓋：楚河漢界 + 主要棋子字。
    sample_chars = list("楚河漢界車馬炮象相士仕將帥卒兵")  # 用 metrics() 檢查是否有字形

    def _supports_all(font: pygame.font.Font) -> bool:
        """用 metrics() 檢查字型是否支援 sample_chars（缺字通常會回傳 None）。"""
        try:
            m = font.metrics("".join(sample_chars))
            return m is not None and all(x is not None for x in m)
        except Exception:
            return False

    def _load_font_file(path: str) -> pygame.font.Font | None:
        """從字型檔載入並檢查字形覆蓋；若成功回傳 Font，否則回傳 None。"""
        if not os.path.exists(path):
            return None
        try:
            f = pygame.font.Font(path, size)
            # pygame.font.Font(path, size) 不一定支援 bold 參數，這裡用 set_bold 來處理
            f.set_bold(bool(bold))
            return f if _supports_all(f) else None
        except Exception:
            return None

    # 你想要「仿宋」：但你的 Windows 目前似乎沒有安裝仿宋（`simfang.ttf` / `fangsong.ttf` 不存在）。
    # 因此我們提供「專案內字型檔」的支援：你若放入 fonts/FangSong.ttf（或 simfang.ttf），就會強制使用。
    local_font_paths = [
        os.path.join(os.path.dirname(__file__), "fonts", "FangSong.ttf"),
        os.path.join(os.path.dirname(__file__), "fonts", "FANGSONG.TTF"),
        os.path.join(os.path.dirname(__file__), "fonts", "simfang.ttf"),
    ]
    for p in local_font_paths:
        f = _load_font_file(p)
        if f is not None:
            return f

    # Windows 系統字型檔 fallback（若你之後安裝了仿宋字型，放在 C:\Windows\Fonts 也能被抓到）
    win_font_paths = [
        r"C:\Windows\Fonts\simfang.ttf",   # 仿宋（若已安裝）
        r"C:\Windows\Fonts\fangsong.ttf",  # 仿宋（另一常見檔名）
        r"C:\Windows\Fonts\FANGSONG.TTF",
        # 其他完整中文 fallback（避免亂碼）
        r"C:\Windows\Fonts\msjh.ttc",      # 微軟正黑體（繁中常見）
        r"C:\Windows\Fonts\mingliu.ttc",   # 細明體
        r"C:\Windows\Fonts\pmingliu.ttc",  # 新細明體
        r"C:\Windows\Fonts\msyh.ttc",      # 微軟雅黑（簡中常見）
        r"C:\Windows\Fonts\simhei.ttf",    # 黑體
        r"C:\Windows\Fonts\simsun.ttc",    # 宋體
    ]
    for p in win_font_paths:
        f = _load_font_file(p)
        if f is not None:
            return f

    # 最後才用 SysFont（名稱解析在不同系統較不穩定）
    candidates = [
        "FangSong",
        "SimFang",
        "STFangsong",
        "仿宋",
        "Microsoft JhengHei",
        "PMingLiU",
        "MingLiU",
        "Microsoft YaHei",
        "SimHei",
        "SimSun",
    ]
    for name in candidates:
        try:
            f = pygame.font.SysFont(name, size, bold=bold)
            if _supports_all(f):
                return f
        except Exception:
            pass

    return pygame.font.Font(None, size)


def get_top_button_rects(button_font: pygame.font.Font) -> tuple[pygame.Rect, pygame.Rect, pygame.Rect]:
    """
    依按鈕文字寬度計算三顆按鈕位置（由右至左：結束遊戲、重新開始、悔棋），
    避免固定寬度導致中文標籤溢出而視覺重疊。
    """
    labels = ("悔棋", "重新開始", "結束遊戲")
    btn_h = 32
    gap = 12  # 按鈕間距
    pad_x = 14  # 文字左右內距
    top = (STATUS_BAR_H - btn_h) // 2
    right_margin = 12

    widths = [max(button_font.size(label)[0] + pad_x * 2, 56) for label in labels]

    x = WINDOW_W - right_margin
    placed: list[pygame.Rect] = []
    for w in reversed(widths):
        x -= w
        placed.append(pygame.Rect(x, top, w, btn_h))
        x -= gap

    quit_rect, restart_rect, undo_rect = placed
    return undo_rect, restart_rect, quit_rect


def draw_button(screen: pygame.Surface, rect: pygame.Rect, font: pygame.font.Font, label: str) -> None:
    """繪製單一按鈕（簡單立體感）。"""
    bg = (255, 255, 255)  # 按鈕底色
    border = (120, 80, 40)  # 邊框色
    pygame.draw.rect(screen, bg, rect, border_radius=8)  # 按鈕底
    pygame.draw.rect(screen, border, rect, width=2, border_radius=8)  # 按鈕邊框
    text = font.render(label, True, (60, 40, 20))  # 文字顏色
    # 限制繪製在按鈕矩形內，避免文字溢出到相鄰按鈕
    prev_clip = screen.get_clip()
    screen.set_clip(rect)
    screen.blit(text, text.get_rect(center=rect.center))
    screen.set_clip(prev_clip)


def draw_status_bar(
    screen: pygame.Surface,
    status_font: pygame.font.Font,
    button_font: pygame.font.Font,
    text: str,
) -> None:
    """在視窗頂部繪製醒目的狀態列 + 操作按鈕（悔棋/重新開始/結束遊戲）。"""
    bar_h = STATUS_BAR_H
    bg = (255, 248, 220)  # 淡黃底（醒目）
    fg = (140, 20, 20) if "思考" in text else (30, 90, 30)  # AI 思考用紅字，輪到玩家用綠字
    pygame.draw.rect(screen, bg, pygame.Rect(0, 0, WINDOW_W, bar_h))  # 頂部背景
    pygame.draw.line(screen, (120, 80, 40), (0, bar_h), (WINDOW_W, bar_h), 2)  # 底部分隔線

    undo_rect, restart_rect, quit_rect = get_top_button_rects(button_font)
    draw_button(screen, undo_rect, button_font, "悔棋")
    draw_button(screen, restart_rect, button_font, "重新開始")
    draw_button(screen, quit_rect, button_font, "結束遊戲")

    # 狀態文字放左側，寬度不超過第一顆按鈕左邊界
    status_area = pygame.Rect(12, 0, max(undo_rect.left - 20, 120), bar_h)
    surf = status_font.render(text, True, fg)
    screen.blit(surf, surf.get_rect(midleft=(status_area.left, status_area.centery)))


def draw_scene(
    screen: pygame.Surface,
    board_font: pygame.font.Font,
    piece_font: pygame.font.Font,
    status_font: pygame.font.Font,
    button_font: pygame.font.Font,
    status_text: str,
    pieces: dict[tuple[int, int], tuple[str, str]],
    dragging_from: tuple[int, int] | None,
    dragging_moves: set[tuple[int, int]],
    dragging_piece: tuple[str, str] | None,
    mouse_x: int,
    mouse_y: int,
) -> None:
    """繪製一整幀畫面並立刻更新到螢幕（用於 AI 思考前強制顯示狀態）。"""
    draw_board(screen, board_font)  # 棋盤
    # 依你的需求：移除「藍點/提示點」顯示，所以這裡不再畫合法落點提示
    draw_pieces(screen, pieces, piece_font)  # 盤面棋子
    if dragging_piece is not None:
        draw_single_piece_at_pixel(screen, dragging_piece, mouse_x, mouse_y, piece_font)  # 拖曳中的棋子
    draw_status_bar(screen, status_font, button_font, status_text)  # 狀態列（頂部）
    pygame.display.flip()  # 更新畫面
    pygame.event.pump()  # 處理視窗事件，避免「未回應」


def main() -> None:
    pygame.init()  # 初始化 pygame（音訊/字型/視窗等模組）
    pygame.display.set_caption("中國象棋 - 第一步（棋盤與初始棋子）")  # 設定視窗標題
    screen = pygame.display.set_mode((WINDOW_W, WINDOW_H))  # 建立視窗 surface（800x900）
    clock = pygame.time.Clock()  # 用來控制主迴圈 FPS

    # 字型（修正中文棋子文字顯示問題）：
    # 使用多候選 + 字型檔 fallback，盡量確保「楚河漢界」與棋子中文字都能正常顯示。
    board_font = load_cjk_font(36)  # 棋盤文字（楚河漢界）字型
    piece_font = load_cjk_font(40, bold=True)  # 棋子文字字型（稍大 + 粗體）
    status_font = load_cjk_font(30)  # 狀態列字型
    button_font = load_cjk_font(22)  # 按鈕字型（較小，避免三顆按鈕文字擠在一起）
    dialog_title_font = load_cjk_font(36, bold=True)  # 勝負提示標題
    dialog_body_font = load_cjk_font(28)  # 勝負提示內文

    global CURRENT_PIECES  # 使用全域變數讓 get_valid_moves 可在未傳入 pieces 時使用
    pieces = get_initial_pieces()  # 取得初始棋子佈局字典
    CURRENT_PIECES = pieces  # 設定目前盤面（供 move 計算使用）

    # --- 回合制設定 ---
    human_side = "red"  # 玩家預設操作紅方
    ai_side = "black"  # AI 預設操作黑方
    current_turn = "red"  # 先手：紅方
    # AI 強度調整：
    # - depth 越大越強，但節點數呈指數成長會更慢
    # - time_limit_sec 是「單步思考」時間上限；配合迭代加深/置換表可在時限內盡量挖深
    ai_config = AIConfig(depth=4, use_tt=True, time_limit_sec=3.5)

    # --- 狀態列 / 勝負 / 悔棋 ---
    status_text = "輪到紅方（玩家）"
    game_over = False  # 是否已結束
    history_stack: list[dict] = []  # 悔棋：每步完成後保存局面快照
    push_history(history_stack, pieces, current_turn, status_text)  # 初始局面入棧

    # --- AI 背景思考狀態（用鎖保護，避免執行緒與主迴圈競態） ---
    ai_lock = threading.Lock()
    ai_job: dict = {"started": False, "done": False, "move": None}

    # --- Drag & Drop 狀態 ---
    dragging_from: tuple[int, int] | None = None
    dragging_piece: tuple[str, str] | None = None
    dragging_moves: set[tuple[int, int]] = set()
    mouse_x, mouse_y = 0, 0

    def cancel_ai_thinking() -> None:
        """取消 AI 背景工作（悔棋或重置時使用）。"""
        with ai_lock:
            ai_job["started"] = False
            ai_job["done"] = False
            ai_job["move"] = None

    def save_current_state(turn: str, status: str) -> None:
        """保存目前局面到 history_stack。"""
        push_history(history_stack, pieces, turn, status)

    def undo_last_moves() -> None:
        """悔棋：對 AI 對戰時一次退回「玩家+AI」兩步（若可能）。"""
        nonlocal pieces, current_turn, status_text, game_over
        nonlocal dragging_from, dragging_piece, dragging_moves
        if len(history_stack) <= 1:
            return
        cancel_ai_thinking()
        # 若輪到玩家（代表 AI 剛下完），悔棋退兩步；否則退一步
        steps = 2 if current_turn == human_side and len(history_stack) >= 3 else 1
        for _ in range(steps):
            if len(history_stack) <= 1:
                break
            history_stack.pop()
        pieces, current_turn, status_text = restore_from_history(history_stack[-1])
        CURRENT_PIECES = pieces
        game_over = False
        dragging_from = None
        dragging_piece = None
        dragging_moves = set()

    def restart_game() -> None:
        """重新開始：回到初始局面並清空歷史。"""
        nonlocal pieces, current_turn, status_text, game_over
        nonlocal dragging_from, dragging_piece, dragging_moves
        cancel_ai_thinking()  # 取消 AI 背景思考
        pieces = get_initial_pieces()  # 重置棋盤
        CURRENT_PIECES = pieces  # 更新全域盤面
        current_turn = "red"  # 紅先
        status_text = "輪到紅方（玩家）"  # 重置狀態文字
        game_over = False  # 清除結束狀態
        history_stack.clear()  # 清空歷史
        push_history(history_stack, pieces, current_turn, status_text)  # 初始局面入棧
        dragging_from = None  # 清空拖曳狀態
        dragging_piece = None
        dragging_moves = set()

    def finalize_move(mover_side: str) -> None:
        """
        某方走完一步後的共用流程：
        1) 檢查將軍 / 勝負
        2) 寫入 history_stack
        3) 若結束則弹出提示視窗
        """
        nonlocal current_turn, status_text, game_over

        winner, msg = evaluate_game_after_move(pieces, mover_side)
        if winner is not None:
            game_over = True
            status_text = msg
            save_current_state(current_turn, status_text)
            draw_scene(
                screen, board_font, piece_font, status_font, button_font, status_text,
                pieces, None, set(), None, mouse_x, mouse_y,
            )
            show_winner_dialog(screen, dialog_title_font, dialog_body_font, msg, clock)
            return

        # 未結束：換對手行棋
        current_turn = opponent_side(mover_side)
        if current_turn == ai_side:
            status_text = f"{msg} — 黑方 AI 思考中..."
        else:
            status_text = f"{msg} — 輪到紅方（玩家）"
        save_current_state(current_turn, status_text)

    def start_ai_thinking() -> None:
        """啟動背景 AI（每回合只啟動一次，避免重複開執行緒導致卡死）。"""
        with ai_lock:
            if ai_job["started"]:  # 已經在算就不要再開
                return
            ai_job["started"] = True
            ai_job["done"] = False
            ai_job["move"] = None

        pieces_snapshot = dict(pieces)  # 盤面快照

        def _think() -> None:
            mv = choose_best_move(
                pieces=pieces_snapshot,
                ai_side=ai_side,
                get_valid_moves_func=get_valid_moves,
                kings_facing_func=kings_facing,
                config=ai_config,
            )
            with ai_lock:
                ai_job["move"] = mv
                ai_job["done"] = True  # 算完（即使 mv 為 None 也算完成）

        threading.Thread(target=_think, daemon=True).start()

    running = True  # 主迴圈控制旗標
    while running:  # 主迴圈：持續處理事件並重畫畫面
        # ----------------------------
        # AI 回合：顯示狀態、背景思考、算完後走一步並換回紅方
        # ----------------------------
        if not game_over and current_turn == ai_side and dragging_piece is None:
            if "思考" not in status_text:
                status_text = "黑方 AI 思考中..."

            with ai_lock:
                need_start = not ai_job["started"]
                ai_finished = ai_job["done"]

            if need_start:
                start_ai_thinking()

            if ai_finished:
                with ai_lock:
                    mv = ai_job["move"]
                    ai_job["started"] = False
                    ai_job["done"] = False
                    ai_job["move"] = None

                if mv is not None:
                    src, dst = mv
                    moving_piece = pieces.get(src)
                    if moving_piece is not None:
                        pieces.pop(src, None)
                        pieces[dst] = moving_piece
                        CURRENT_PIECES = pieces
                        finalize_move(ai_side)  # AI 走完：檢查將軍/勝負/寫入 history
                else:
                    current_turn = human_side
                    status_text = "輪到紅方（玩家）"

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                running = False
            elif event.type == pygame.KEYDOWN and event.key in (pygame.K_u, pygame.K_z):
                undo_last_moves()  # 悔棋（U 或 Z）
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_r and game_over:
                # 重新開始
                pieces = get_initial_pieces()
                CURRENT_PIECES = pieces
                current_turn = "red"
                status_text = "輪到紅方（玩家）"
                game_over = False
                history_stack.clear()
                push_history(history_stack, pieces, current_turn, status_text)
                cancel_ai_thinking()
                dragging_from = None
                dragging_piece = None
                dragging_moves = set()
            elif event.type == pygame.MOUSEMOTION:
                mouse_x, mouse_y = event.pos
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                mouse_x, mouse_y = event.pos
                # 先處理頂部按鈕點擊（不受回合/結束狀態限制）
                undo_rect, restart_rect, quit_rect = get_top_button_rects(button_font)
                if undo_rect.collidepoint(mouse_x, mouse_y):
                    undo_last_moves()  # 按下「悔棋」
                    continue
                if restart_rect.collidepoint(mouse_x, mouse_y):
                    restart_game()  # 按下「重新開始」
                    continue
                if quit_rect.collidepoint(mouse_x, mouse_y):
                    running = False  # 按下「結束遊戲」→ 關閉遊戲
                    continue

                if game_over or current_turn != human_side:
                    continue
                bpos = screen_to_board(mouse_x, mouse_y)  # 嘗試吸附到棋盤座標
                if bpos is None:  # 沒點到落子點附近
                    continue  # 不做任何事
                if bpos not in pieces:  # 點到空格
                    continue  # 空格不能開始拖曳
                if pieces[bpos][0] != human_side:  # 若點到的是對方棋子
                    continue  # 不能拖曳對方棋子（回合制）

                # 正式開始拖曳：把棋子從盤面暫時拿起（畫面上改由「跟隨滑鼠」呈現）
                dragging_from = bpos  # 記錄拖曳起點
                dragging_piece = pieces[bpos]  # 記錄拖曳的棋子內容
                dragging_moves = get_valid_moves(dragging_piece, dragging_from, pieces)  # 計算合法落點（提示 + 放開判定）
                pieces.pop(bpos, None)  # 從盤面移除（避免畫兩顆）
                CURRENT_PIECES = pieces  # 更新盤面（注意：這裡盤面暫時少一顆正在拖曳的棋子）

            elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:  # 放開左鍵 → 嘗試落子
                mouse_x, mouse_y = event.pos  # 記錄放開瞬間滑鼠位置
                if dragging_from is None or dragging_piece is None:  # 若目前沒在拖曳
                    continue  # 不處理

                drop_pos = screen_to_board(mouse_x, mouse_y)  # 放開位置吸附到棋盤座標（可能為 None）

                if drop_pos is not None and drop_pos in dragging_moves:
                    # 先清空提示點（避免因事件處理順序造成提示殘留）
                    dragging_from_old = dragging_from  # 暫存（若後面需要用到）
                    dragging_from = None
                    dragging_moves = set()

                    pieces[drop_pos] = dragging_piece
                    CURRENT_PIECES = pieces
                    cancel_ai_thinking()
                    finalize_move(human_side)  # 玩家走完：檢查將軍/勝負/寫入 history
                    if not game_over:
                        draw_scene(
                            screen, board_font, piece_font, status_font, button_font, status_text,
                            pieces, None, set(), None, mouse_x, mouse_y,
                        )
                else:
                    # 若放在不合法位置：棋子回彈回原位（放回 dragging_from）
                    pieces[dragging_from] = dragging_piece  # 還原

                # 結束拖曳狀態並清空提示
                dragging_from = None  # 清空起點
                dragging_piece = None  # 清空拖曳棋子
                dragging_moves = set()  # 清空合法落點提示
                CURRENT_PIECES = pieces  # 更新盤面

        draw_scene(
            screen,
            board_font,
            piece_font,
            status_font,
            button_font,
            status_text,
            pieces,
            dragging_from,
            dragging_moves,
            dragging_piece,
            mouse_x,
            mouse_y,
        )
        clock.tick(60)  # 限制 FPS；AI 在背景算，主迴圈仍可刷新畫面

    pygame.quit()  # 正常關閉 pygame
    sys.exit(0)  # 以 0 結束程式（代表成功）


if __name__ == "__main__":  # 當此檔案被直接執行（不是被 import）時
    main()  # 呼叫主程式入口

