# -*- coding: utf-8 -*-
"""マクロ実行エンジン。決めた間隔でクリックやキーを最大3つまで順番に送りつづける。

  * 左 / 右 / 中クリック、サイドボタン、または任意のキー（3つまで混在可）
  * 間隔はミリ秒指定（parse_secs/fmt_secsで「2秒」「1分30秒」のような書き方も読める）
  * 対象アプリが最前面のときだけ動かす安全装置つき（既定オン）
  * グローバルホットキーで入切
  * 実際の操作を記録して3ステップに自動で反映する SequenceRecorder（マウス+キーボード）

送信はSendInput。マウスは押す/離すを1組で送る。
"""
from __future__ import annotations

import ctypes
import threading
import time
from ctypes import wintypes

import winapi as wa

user32 = wa.user32
kernel32 = wa.kernel32

MOUSEEVENTF = {
    "left": (0x0002, 0x0004),
    "right": (0x0008, 0x0010),
    "middle": (0x0020, 0x0040),
    # サイドボタンは押す/離すの旗が共通で、どちらのボタンかはmouseDataで渡す
    "x1": (0x0080, 0x0100),
    "x2": (0x0080, 0x0100),
}
# サイドボタンの番号。1=手前（戻る）、2=奥（進む）
MOUSE_DATA = {"x1": 1, "x2": 2}

ACTIONS = (
    ("left", "左クリック"),
    ("right", "右クリック"),
    ("middle", "中クリック"),
    ("x1", "サイドボタン1（戻る）"),
    ("x2", "サイドボタン2（進む）"),
    ("key", "キー（下で指定）"),
)
DEFAULT_ACTION = "left"

# マクロの出しかた。設定で選ぶものではなく、どちらもいつでも使える。
#   hold   … 左クリックを押しているあいだだけ送る（既定 Ctrl+R）
#   always … 入れたらずっと送りつづける（既定 Ctrl+T）
# 撃つ中身（なにを・何ミリ秒ごとに）は共通。出しかたが違うだけ。
MODES = (
    ("hold", "押しっぱなしで実行"),
    ("always", "ずっと実行"),
)
DEFAULT_MODE = "hold"


def mode_label(name):
    for k, lbl in MODES:
        if k == name:
            return lbl
    return name


MAX_RECORD_STEPS = 500        # 記録を止め忘れて延々続けてしまったときの安全弁


# ------------------------------------------------- 秒・分の読み書き
# ミリ秒で入れさせると桁を間違える。「0.5」「2秒」「1分30秒」「1:30」で書く。
_UNITS = (("ミリ秒", 0.001), ("ミリ", 0.001), ("ms", 0.001),
          ("分", 60.0), ("m", 60.0), ("秒", 1.0), ("s", 1.0))


def parse_secs(text, default=None):
    """「0.5」「2秒」「1分30秒」「1:30」を秒にする。読めなければdefault。"""
    t = (text or "").strip().lower()
    if not t:
        return default
    t = t.translate(str.maketrans("０１２３４５６７８９．：",
                                  "0123456789.:"))
    if ":" in t:                       # 1:30 = 1分30秒
        got = t.split(":")
        try:
            mm, ss = float(got[0] or 0), float(got[1] or 0)
        except ValueError:
            return default
        return mm * 60.0 + ss
    total, rest, hit = 0.0, t, False
    for unit, mul in _UNITS:
        i = rest.find(unit)
        while i >= 0:
            head = rest[:i]
            num = "".join(c for c in head if c.isdigit() or c == ".")
            if num:
                try:
                    total += float(num) * mul
                    hit = True
                except ValueError:
                    pass
            rest = rest[i + len(unit):]
            i = rest.find(unit)
    if hit:
        num = "".join(c for c in rest if c.isdigit() or c == ".")
        if num:
            try:
                total += float(num)
            except ValueError:
                pass
        return total
    try:
        return float(t)                # 単位なしは秒とみなす
    except ValueError:
        return default


def fmt_secs(sec):
    """秒を、書き戻せる形の文字で。"""
    try:
        sec = float(sec)
    except (TypeError, ValueError):
        return "0"
    if sec >= 60:
        m, s = int(sec // 60), sec - int(sec // 60) * 60
        if abs(s) < 0.0005:
            return "%d分" % m
        return "%d分%s秒" % (m, ("%.3f" % s).rstrip("0").rstrip("."))
    return ("%.3f" % sec).rstrip("0").rstrip(".") or "0"


def action_label(name):
    if name == "move_path":
        return "🖱 動き"
    for k, lbl in ACTIONS:
        if k == name:
            return lbl
    return name


# ---------------------------------------------------------------- 送信
def _mouse_input(flag, data=0):
    return wa.INPUT(type=wa.INPUT_MOUSE,
                    u=wa._INPUTUNION(mi=wa.MOUSEINPUT(dx=0, dy=0, mouseData=int(data),
                                                      dwFlags=flag, time=0,
                                                      dwExtraInfo=0)))


def mouse_hold(button="left", down=True):
    """マウスのボタンを押しっぱなしにする／離す。"""
    pair = MOUSEEVENTF.get(button)
    if not pair:
        return False
    a = _mouse_input(pair[0] if down else pair[1], MOUSE_DATA.get(button, 0))
    return user32.SendInput(1, ctypes.byref(a), ctypes.sizeof(wa.INPUT)) == 1


def click(button="left", hold_ms=20):
    """いまカーソルがある場所でクリックする。"""
    pair = MOUSEEVENTF.get(button)
    if not pair:
        return False
    down, up = pair
    data = MOUSE_DATA.get(button, 0)
    size = ctypes.sizeof(wa.INPUT)
    a, b = _mouse_input(down, data), _mouse_input(up, data)
    if user32.SendInput(1, ctypes.byref(a), size) != 1:
        return False
    if hold_ms > 0:
        wa.sleep(hold_ms / 1000.0)
    user32.SendInput(1, ctypes.byref(b), size)
    return True


def key_hold(vk, scan=None, down=True):
    """キーを押しっぱなしにする／離す。"""
    vk = int(vk)
    if not scan:
        scan = wa.scancode_of(vk)
    if not scan:
        return False
    a = wa._make_key(scan, vk in wa.EXTENDED_VKS, not down)
    return user32.SendInput(1, ctypes.byref(a), ctypes.sizeof(wa.INPUT)) == 1


def press_vk(vk, scan=None, hold_ms=20):
    """仮想キーコードでキーを1回押す。スキャンコードで送る。"""
    vk = int(vk)
    if not scan:
        scan = wa.scancode_of(vk)
    if not scan:
        return False
    ext = vk in wa.EXTENDED_VKS
    down = wa._make_key(scan, ext, False)
    up = wa._make_key(scan, ext, True)
    size = ctypes.sizeof(wa.INPUT)
    if user32.SendInput(1, ctypes.byref(down), size) != 1:
        return False
    if hold_ms > 0:
        wa.sleep(hold_ms / 1000.0)
    user32.SendInput(1, ctypes.byref(up), size)
    return True


# ------------------------------------------------------- ウィンドウ直送り
# 最前面でなくても届くが、生入力(RawInput/DirectInput)しか見ないアプリには
# 効かない。UIの「ためす」で確かめてから使うこと。効かなければswap（一瞬だけ
# 前に出す）を使う。
WM_LBUTTONDOWN, WM_LBUTTONUP = 0x0201, 0x0202
WM_RBUTTONDOWN, WM_RBUTTONUP = 0x0204, 0x0205
WM_MBUTTONDOWN, WM_MBUTTONUP = 0x0207, 0x0208
WM_XBUTTONDOWN, WM_XBUTTONUP = 0x020B, 0x020C
WM_MOUSEMOVE = 0x0200
MK_LBUTTON, MK_RBUTTON, MK_MBUTTON = 0x0001, 0x0002, 0x0010
MK_XBUTTON1, MK_XBUTTON2 = 0x0020, 0x0040

POST_BUTTON = {
    "left": (WM_LBUTTONDOWN, WM_LBUTTONUP, MK_LBUTTON, 0),
    "right": (WM_RBUTTONDOWN, WM_RBUTTONUP, MK_RBUTTON, 0),
    "middle": (WM_MBUTTONDOWN, WM_MBUTTONUP, MK_MBUTTON, 0),
    "x1": (WM_XBUTTONDOWN, WM_XBUTTONUP, MK_XBUTTON1, 1),
    "x2": (WM_XBUTTONDOWN, WM_XBUTTONUP, MK_XBUTTON2, 2),
}


def _wparam(mk, xb):
    """サイドボタンは上位に番号、下位に押されている印。"""
    return ((int(xb) & 0xFFFF) << 16) | (int(mk) & 0xFFFF)


SEND_MODES = (
    ("input", "ふつうに送る（最前面のアプリに届きます）"),
    ("post", "ウィンドウに直接送る（裏でもOK・効かないアプリもある）"),
    ("swap", "一瞬だけ前に出して送り、すぐ戻す（たいてい効く・ちらつく）"),
)
DEFAULT_SEND_MODE = "input"


def send_mode_label(mode):
    for k, lbl in SEND_MODES:
        if k == mode:
            return lbl
    return mode


def _cursor_in_client(hwnd):
    """いまのマウス位置を、そのウィンドウの中の座標に直す。"""
    pt = wintypes.POINT()
    if not user32.GetCursorPos(ctypes.byref(pt)):
        return 0, 0
    if not user32.ScreenToClient(hwnd, ctypes.byref(pt)):
        return 0, 0
    rect = wintypes.RECT()
    if user32.GetClientRect(hwnd, ctypes.byref(rect)):
        if not (0 <= pt.x <= rect.right and 0 <= pt.y <= rect.bottom):
            return rect.right // 2, rect.bottom // 2
    return pt.x, pt.y


def post_click(hwnd, button="left", hold_ms=20):
    got = POST_BUTTON.get(button)
    if not got or not hwnd:
        return False
    down_msg, up_msg, mk, xb = got
    x, y = _cursor_in_client(hwnd)
    lp = (int(y) & 0xFFFF) << 16 | (int(x) & 0xFFFF)
    user32.PostMessageW(hwnd, WM_MOUSEMOVE, 0, lp)
    if not user32.PostMessageW(hwnd, down_msg, _wparam(mk, xb), lp):
        return False
    wa.sleep(max(0.0, hold_ms / 1000.0))
    user32.PostMessageW(hwnd, up_msg, _wparam(0, xb), lp)
    return True


def post_mouse_hold(hwnd, button="left", down=True):
    got = POST_BUTTON.get(button)
    if not got or not hwnd:
        return False
    down_msg, up_msg, mk, xb = got
    x, y = _cursor_in_client(hwnd)
    lp = (int(y) & 0xFFFF) << 16 | (int(x) & 0xFFFF)
    if down:
        user32.PostMessageW(hwnd, WM_MOUSEMOVE, mk, lp)
        return bool(user32.PostMessageW(hwnd, down_msg, _wparam(mk, xb), lp))
    return bool(user32.PostMessageW(hwnd, up_msg, _wparam(0, xb), lp))


def post_key_hold(hwnd, vk, scan=None, down=True, again=False):
    if not hwnd or not vk:
        return False
    if not scan:
        scan = wa.scancode_of(vk)
    lp = 1 | ((scan or 0) << 16)
    if down:
        if again:
            lp |= (1 << 30)
        return bool(user32.PostMessageW(hwnd, wa.WM_KEYDOWN, int(vk), lp))
    return bool(user32.PostMessageW(hwnd, wa.WM_KEYUP, int(vk),
                                    lp | (1 << 30) | (1 << 31)))


def post_vk(hwnd, vk, scan=None, hold_ms=20):
    if not hwnd or not vk:
        return False
    if not scan:
        scan = wa.scancode_of(vk)
    down = 1 | ((scan or 0) << 16)
    up = down | (1 << 30) | (1 << 31)
    if not user32.PostMessageW(hwnd, wa.WM_KEYDOWN, int(vk), down):
        return False
    wa.sleep(max(0.0, hold_ms / 1000.0))
    user32.PostMessageW(hwnd, wa.WM_KEYUP, int(vk), up)
    return True


def steps_of(cfg):
    """設定から操作の並びを作る。空なら、1操作として読む。

    ステップの数に上限は無い（記録した一連の操作をまるごと持てる）。
    "pos": [x, y] が付いているマウス操作は、その画面座標へカーソルを
    動かしてからクリックする（卵の孵化のように、決まった場所を押しつづける
    作業のため）。付いていなければ、いまカーソルがある場所を押す。
    """
    got = []
    for st in (cfg.get("steps") or []):
        act = (st.get("action") or "").strip()
        if not act or act == "none":
            continue
        got.append({"action": act,
                    "key_vk": st.get("key_vk") or 0,
                    "key_scan": st.get("key_scan") or 0,
                    "hold_ms": st.get("hold_ms", cfg.get("hold_ms", 20)),
                    "gap_ms": st.get("gap_ms", 120),
                    "every": max(1, int(st.get("every") or 1)),
                    "pos": st.get("pos"),
                    "path": st.get("path")})
    if got:
        return got
    return [{"action": cfg.get("action") or DEFAULT_ACTION,
             "key_vk": cfg.get("key_vk") or 0,
             "key_scan": cfg.get("key_scan") or 0,
             "hold_ms": cfg.get("hold_ms", 20),
             "gap_ms": 0, "every": 1, "pos": cfg.get("pos")}]


def due(step, cycle):
    """この回に、その操作を混ぜるか。every=3なら「3回に1度」。"""
    ev = max(1, int(step.get("every") or 1))
    if ev <= 1 or cycle is None:
        return True
    return cycle % ev == 0


def send_seq(cfg, hwnd=None, halt=None, cycle=None):
    """操作の並びを、あいだを空けながら順に送る。

    各ステップの gap_ms は「そのステップのあとに次まで待つ時間」という意味で
    統一している（手で編集する「次まで」欄と、記録した実測の間隔の両方）。
    """
    steps = [st for st in steps_of(cfg) if due(st, cycle)]
    sent, why = 0, ""
    for i, st in enumerate(steps):
        if halt is not None and halt.is_set():
            break
        if st.get("action") == "move_path":
            ok = send_move_path(st, halt)
        else:
            one = dict(cfg)
            one.update(st)
            ok, msg = send_once(one, hwnd)
            if not ok and msg:
                why = msg
        if ok:
            sent += 1
        if i + 1 < len(steps):
            gap = max(0.0, float(st.get("gap_ms") or 0) / 1000.0)
            if halt is not None:
                if halt.wait(gap):
                    break
            elif gap:
                wa.sleep(gap)
    return sent > 0, why


def send_move_path(step, halt=None):
    """記録した「一連の動き」を、そのときの速さのまま再現する。

    経路の各点は [x, y, 直前の点からの経過ミリ秒]。マウスの見た目位置(SetCursorPos)
    と、本物の移動と同じ形の入力(move_abs)の両方を送る。halt を渡せば、
    マクロを止めたときに経路の途中でもすぐ抜けられる。
    """
    sent = False
    for x, y, dt_ms in (step.get("path") or []):
        if halt is not None and halt.is_set():
            break
        wait = max(0.0, float(dt_ms or 0) / 1000.0)
        if wait:
            if halt is not None:
                if halt.wait(wait):
                    break
            else:
                wa.sleep(wait)
        wa.move_abs(x, y)
        wa.set_cursor_pos(x, y)
        sent = True
    return sent


def send_once(cfg, hwnd=None):
    """設定どおりに1回送る。(送れたか, 説明) を返す。"""
    mode = cfg.get("send_mode") or DEFAULT_SEND_MODE
    act = cfg.get("action") or DEFAULT_ACTION
    vk, scan = cfg.get("key_vk") or 0, cfg.get("key_scan") or 0
    hold = cfg.get("hold_ms", 20)
    if act == "key" and not vk:
        return False, "さきに送るキーを決めてください"

    pos = cfg.get("pos")
    if pos and act != "key":
        # SetCursorPosだけだと見た目のカーソルが動くだけで「移動した」という
        # 入力イベントが発生しない。Raw Inputで直前の移動からクリック位置を
        # 拾うゲームのために、本物の移動と同じ形のSendInputも送っておく。
        wa.move_abs(pos[0], pos[1])
        wa.sleep(0.01)
        wa.set_cursor_pos(pos[0], pos[1])   # 丸め誤差を吸収して正確な座標に直す
        wa.sleep(0.02)          # カーソルが動いたのをOSが拾うのを待つ

    if mode == "input":
        ok = press_vk(vk, scan, hold) if act == "key" else click(act, hold)
        return bool(ok), ""

    if hwnd is None:
        hwnd = wa.find_window(cfg.get("target") or "")
    if not hwnd:
        return False, "%s のウィンドウが見つかりません" % (cfg.get("target")
                                                          or "対象")
    if mode == "post":
        ok = (post_vk(hwnd, vk, scan, hold) if act == "key"
              else post_click(hwnd, act, hold))
        return bool(ok), ""
    if mode == "swap":
        prev = user32.GetForegroundWindow()
        if not wa.force_foreground(hwnd):
            return False, "前に出せませんでした"
        wa.sleep(0.12)
        ok = press_vk(vk, scan, hold) if act == "key" else click(act, hold)
        wa.sleep(0.04)
        if prev and prev != hwnd:
            wa.force_foreground(prev)
        return bool(ok), ""
    return False, "知らない送り方です: %s" % mode


class Runner(threading.Thread):
    """止めるまで操作を送りつづけるスレッド。

    設定はget_cfg()で毎回読み直すので、動かしたまま間隔を変えられる。
    """

    def __init__(self, get_cfg, gate=None):
        super().__init__(daemon=True)
        self.get_cfg = get_cfg
        # gateを渡すと、それがTrueを返しているあいだだけ撃つ。
        self.gate = gate
        self._halt = threading.Event()
        self.count = 0
        self.cycle = 0
        self.waiting = False
        self.holding = False
        self.finished = False

    def stop(self):
        self._halt.set()

    def run(self):
        while not self._halt.is_set():
            c = self.get_cfg()
            if self.gate is not None and not self.gate():
                self.holding = False
                self._halt.wait(0.01)
                continue
            self.holding = True
            if c.get("only_target") and not wa.matches(c.get("target") or ""):
                self.waiting = True
                self._halt.wait(0.15)
                continue
            self.waiting = False
            hwnd = None
            if (c.get("send_mode") or DEFAULT_SEND_MODE) != "input":
                hwnd = wa.find_window_cached(c.get("target") or "")
                if not hwnd:
                    self.waiting = True
                    self._halt.wait(0.5)
                    continue
            self.cycle += 1
            ok, _why = send_seq(c, hwnd, self._halt, self.cycle)
            if ok:
                self.count += 1
            limit = int(c.get("limit") or 0)
            if limit and self.count >= limit:
                self.finished = True
                break
            waited = 0.0
            while not self._halt.is_set():
                want = max(0.001,
                           int(self.get_cfg().get("interval_ms") or 100) / 1000.0)
                if waited >= want:
                    break
                self._halt.wait(min(0.2, want - waited))
                waited += min(0.2, want - waited)


class Holder(threading.Thread):
    """止めるまで押しっぱなしにする（1つ目の操作だけ）。

    大事なのは**必ず離すこと**。押したままスレッドが終わると、キーが
    押されっぱなしのまま残って他のアプリまで巻き添えになる。
    """

    def __init__(self, get_cfg):
        super().__init__(daemon=True)
        self.get_cfg = get_cfg
        self._halt = threading.Event()
        self.down = False
        self.waiting = False
        self.error = ""

    def stop(self):
        self._halt.set()

    def _send(self, c, hwnd, down, again=False):
        st = steps_of(c)[0]
        act = st.get("action") or DEFAULT_ACTION
        mode = c.get("send_mode") or DEFAULT_SEND_MODE
        vk, scan = st.get("key_vk") or 0, st.get("key_scan") or 0
        if down and act != "key" and st.get("pos"):
            wa.set_cursor_pos(*st["pos"])
            wa.sleep(0.02)
        if mode == "post":
            if act == "key":
                return post_key_hold(hwnd, vk, scan, down, again)
            return post_mouse_hold(hwnd, act, down)
        if act == "key":
            return key_hold(vk, scan, down)
        return mouse_hold(act, down)

    def _release(self, c, hwnd):
        if self.down:
            self._send(c, hwnd, False)
            self.down = False

    def run(self):
        c, hwnd = self.get_cfg(), None
        try:
            while not self._halt.is_set():
                c = self.get_cfg()
                mode = c.get("send_mode") or DEFAULT_SEND_MODE
                if c.get("only_target") and not wa.matches(c.get("target") or ""):
                    self._release(c, hwnd)
                    self.waiting = True
                    self._halt.wait(0.15)
                    continue
                hwnd = None
                if mode != "input":
                    hwnd = wa.find_window_cached(c.get("target") or "")
                    if not hwnd:
                        self._release(c, hwnd)
                        self.waiting = True
                        self._halt.wait(0.5)
                        continue
                self.waiting = False
                if self._send(c, hwnd, True, again=self.down):
                    self.down = True
                self._halt.wait(0.05)
        finally:
            self._release(c, hwnd)


# ------------------------------------------------- 右クリックで止める
# 押されたら止めたいだけなので、フックは**覗くだけ**にして必ず次へ流す。
# 大事なのは「自分が送った右クリックでは止まらない」こと。低レベルフックなら
# 注入された入力に印(LLMHF_INJECTED)が付くので、それで分ける。
WH_MOUSE_LL = 14
WM_LBUTTONDOWN_LL = 0x0201
WM_LBUTTONUP_LL = 0x0202
WM_RBUTTONDOWN_LL = 0x0204
WM_RBUTTONUP_LL = 0x0205
LLMHF_INJECTED = 0x00000001
ULONG_PTR = wintypes.WPARAM


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = (("pt", wintypes.POINT), ("mouseData", wintypes.DWORD),
                ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ULONG_PTR))


MOUSE_HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_int, wintypes.WPARAM,
                                    ctypes.POINTER(MSLLHOOKSTRUCT))


class CancelWatch(threading.Thread):
    """本物の右クリックを見張って、押されたらcallbackを呼ぶ。

    callbackはフックの中から呼ばれるので、**すぐ返ること**。
    guardを渡すと、それがTrueを返したときだけ呼ぶ。
    """

    def __init__(self, callback, button="right", guard=None):
        super().__init__(daemon=True)
        self.callback = callback
        self.guard = guard
        self.button = button
        self.msg = (WM_LBUTTONDOWN_LL if button == "left"
                    else WM_RBUTTONDOWN_LL)
        self._tid = 0
        self._hook = None
        self._proc = None
        self.ready = threading.Event()
        self.ok = False

    def _on_event(self, code, wparam, lparam):
        try:
            if (code >= 0 and wparam == self.msg
                    and not (lparam.contents.flags & LLMHF_INJECTED)
                    and (self.guard is None or self.guard())):
                self.callback()
        except Exception:
            pass
        return user32.CallNextHookEx(None, code, wparam, lparam)

    def run(self):
        self._tid = kernel32.GetCurrentThreadId()
        self._proc = MOUSE_HOOKPROC(self._on_event)
        self._hook = user32.SetWindowsHookExW(WH_MOUSE_LL, self._proc, None, 0)
        self.ok = bool(self._hook)
        self.ready.set()
        if not self.ok:
            return
        msg = MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            pass
        user32.UnhookWindowsHookEx(self._hook)
        self._hook = None

    def stop(self):
        if self._tid:
            user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)


class HoldWatch(threading.Thread):
    """ボタンを押しているあいだheldを立てておく。

    GetAsyncKeyStateでは駄目で、フックでないといけない。自分が送った
    クリックも「押された」に見えてしまい、指を離しても止まらなくなる。
    """

    def __init__(self, button="left", guard=None):
        super().__init__(daemon=True)
        self.button = button
        self.guard = guard
        self.since = 0.0
        self.down = (WM_LBUTTONDOWN_LL if button == "left"
                     else WM_RBUTTONDOWN_LL)
        self.up = WM_LBUTTONUP_LL if button == "left" else WM_RBUTTONUP_LL
        self.held = False
        self._tid = 0
        self._hook = None
        self._proc = None
        self.ready = threading.Event()
        self.ok = False

    def _on_event(self, code, wparam, lparam):
        try:
            if code >= 0 and not (lparam.contents.flags & LLMHF_INJECTED):
                if wparam == self.down:
                    self.held = bool(self.guard is None or self.guard())
                    self.since = time.time() if self.held else 0.0
                elif wparam == self.up:
                    self.held = False
                    self.since = 0.0
        except Exception:
            pass
        return user32.CallNextHookEx(None, code, wparam, lparam)

    def run(self):
        self._tid = kernel32.GetCurrentThreadId()
        self._proc = MOUSE_HOOKPROC(self._on_event)
        self._hook = user32.SetWindowsHookExW(WH_MOUSE_LL, self._proc, None, 0)
        self.ok = bool(self._hook)
        self.ready.set()
        if not self.ok:
            return
        msg = MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            pass
        user32.UnhookWindowsHookEx(self._hook)
        self._hook = None

    def held_for(self):
        """押しつづけている秒数。離していれば0。"""
        return (time.time() - self.since) if (self.held and self.since) else 0.0

    def stop(self):
        self.held = False
        self.since = 0.0
        if self._tid:
            user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)


VK_LBUTTON = 0x01
_MOUSE_VK_ACTIONS = {0x01: "left", 0x02: "right", 0x04: "middle",
                    0x05: "x1", 0x06: "x2"}


MAX_PATH_POINTS = 4000        # 1回の動きにつける経路の点の数の安全弁


class SequenceRecorder(threading.Thread):
    """実際の操作（マウスの動き・クリック・キー押下）を、一連の流れとして記録する。

    低レベルフック(SetWindowsHookEx)ではなく GetAsyncKeyState による
    ポーリングで拾う。ゲームによっては（とくに管理者権限で動いているとき）
    UIPIに阻まれてフックが本物の入力を拾えないことがあり、記録できない
    原因になっていた。ポーリングはそれを迂回できる
    （Meridianの「たまごマクロ」の位置記録と同じ、実績のあるやり方）。

    クリック/キーだけでなく、そのあいだのマウスの動きも "move_path" という
    種類のステップとして丸ごと記録する（点ごとの座標と直前からの経過時間）。
    テレポートするような移動ではなく本物の軌跡で再現したほうが、Raw Input
    で判定しているゲームでクリックが通りやすくなることがあるため。

    どのステップの gap_ms も「そのステップのあと、次まで待つ時間」という
    統一した意味にしている。記録中は逆に「直前の出来事からの経過時間」しか
    分からないので、新しい出来事が起きた瞬間に**ひとつ前のステップ**の
    gap_ms を実測値で確定させる（_mark_gap）。

    want=0なら無制限（stop()が呼ばれる、またはEscで終わるまで記録する）。
    exclude_vksに渡したキー／ボタン（記録の開始・終了に使ったホットキー等）
    は、それ自体を操作として記録しない。
    """
    _MOD_VKS = {0x10, 0x11, 0x12, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5, 0x5B, 0x5C}
    _VK_ESCAPE = 0x1B

    def __init__(self, want=0, on_step=None, exclude_vks=None):
        super().__init__(daemon=True)
        self.want = max(0, int(want))
        self.on_step = on_step
        self.exclude = set(exclude_vks or ())
        self.steps = []
        self._last_t = None
        self._halt = threading.Event()
        self.done = False
        self.cancelled = False

    def stop(self):
        self._halt.set()

    def _emit(self, st):
        self.steps.append(st)
        if self.on_step:
            try:
                self.on_step(len(self.steps), st)
            except Exception:
                pass
        if ((self.want and len(self.steps) >= self.want)
                or len(self.steps) >= MAX_RECORD_STEPS):
            self.done = True
            self.stop()

    def _mark_gap(self, now):
        """直前のステップの「次まで」を、いま確定した実測の間隔で埋める。"""
        if self.steps and self._last_t is not None:
            self.steps[-1]["gap_ms"] = max(0, int((now - self._last_t) * 1000))
        self._last_t = now

    def _push_action(self, action, vk=0, scan=0, pos=None):
        now = time.time()
        self._mark_gap(now)
        self._emit({"action": action, "key_vk": vk, "key_scan": scan,
                   "gap_ms": 0, "every": 1, "pos": list(pos) if pos else None})

    def _flush_path(self, buf):
        """溜めておいた移動の点を、1つの"move_path"ステップにして確定する。"""
        if self.done or len(buf) < 2:
            return
        start_t = buf[0][2]
        self._mark_gap(start_t)
        path, prev_t = [], start_t
        for x, y, t in buf:
            path.append([x, y, max(0, int((t - prev_t) * 1000))])
            prev_t = t
        self._emit({"action": "move_path", "path": path, "gap_ms": 0,
                   "every": 1, "pos": None, "key_vk": 0, "key_scan": 0})
        self._last_t = buf[-1][2]

    def run(self):
        # 1〜255 を見る。1,2,4,5,6 はマウスの左/右/中/サイドボタン
        # （8未満なので、ここを8からにすると丸ごと監視から漏れてしまう）
        watch = [vk for vk in range(1, 256) if vk not in self._MOD_VKS]
        # 記録を始めた時点ですでに押さえられているキー（開始に使ったホット
        # キーなど）は、離されるまで「まだ押されている」ことにして無視する
        prev = {vk: bool(user32.GetAsyncKeyState(vk) & 0x8000) for vk in watch}
        p0 = wa.cursor_pos()
        buf = [(p0[0], p0[1], time.time())]
        while not self._halt.is_set() and not self.done:
            pos = wa.cursor_pos()
            if pos != buf[-1][:2]:
                buf.append((pos[0], pos[1], time.time()))
                if len(buf) > MAX_PATH_POINTS:
                    self._flush_path(buf)
                    buf = [(pos[0], pos[1], time.time())]
            for vk in watch:
                down = bool(user32.GetAsyncKeyState(vk) & 0x8000)
                if down and not prev[vk]:
                    if vk == self._VK_ESCAPE:
                        self.cancelled = not self.steps
                        self.done = True
                        prev[vk] = down
                        break
                    if vk not in self.exclude:
                        self._flush_path(buf)
                        buf = [(pos[0], pos[1], time.time())]
                        act = _MOUSE_VK_ACTIONS.get(vk)
                        if act:
                            self._push_action(act, pos=pos)
                        else:
                            self._push_action("key", vk, wa.scancode_of(vk))
                prev[vk] = down
                if self.done:
                    break
            if not self.done:
                self._halt.wait(0.015)
        self.done = True


class PositionRecorder(threading.Thread):
    """左クリックをwant回ぶん見張って、押した場所（画面座標）を覚える。

    卵の孵化のように「決まった場所を押しつづける」操作のための、位置の
    登録用。フックは使わず、キーの状態を細かく見に行くだけ。取りこぼしても
    次のクリックで拾えるし、他のアプリの邪魔をしない。
    """

    def __init__(self, want=1, on_point=None):
        super().__init__(daemon=True)
        self.want = max(1, int(want))
        self.on_point = on_point
        self.points = []
        self._halt = threading.Event()
        self.done = False

    def stop(self):
        self._halt.set()

    def run(self):
        # 「登録する」を押したクリック自体を拾わないよう、指が離れるまで待つ
        while not self._halt.is_set():
            if not (user32.GetAsyncKeyState(VK_LBUTTON) & 0x8000):
                break
            self._halt.wait(0.02)
        was_down = False
        while not self._halt.is_set() and len(self.points) < self.want:
            down = bool(user32.GetAsyncKeyState(VK_LBUTTON) & 0x8000)
            if down and not was_down:
                p = wa.cursor_pos()
                self.points.append(p)
                if self.on_point:
                    try:
                        self.on_point(len(self.points), p)
                    except Exception:
                        pass
            was_down = down
            self._halt.wait(0.015)
        self.done = True


# ---------------------------------------------------------------- ホットキー
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN = 0x0001, 0x0002, 0x0004, 0x0008
MOD_NOREPEAT = 0x4000


class MSG(ctypes.Structure):
    _fields_ = (("hwnd", wintypes.HWND), ("message", wintypes.UINT),
                ("wParam", wintypes.WPARAM), ("lParam", wintypes.LPARAM),
                ("time", wintypes.DWORD), ("pt_x", wintypes.LONG),
                ("pt_y", wintypes.LONG))


class Hotkey(threading.Thread):
    """グローバルホットキーを1つ登録して、押されたらcallbackを呼ぶ。"""

    def __init__(self, mods, vk, callback, hk_id=1):
        super().__init__(daemon=True)
        self.mods = int(mods)
        self.vk = int(vk)
        self.hk_id = int(hk_id)
        self.callback = callback
        self.ready = threading.Event()
        self.ok = False
        self.error = ""
        self._tid = 0

    def run(self):
        self._tid = kernel32.GetCurrentThreadId()
        self.ok = bool(user32.RegisterHotKey(None, self.hk_id,
                                             self.mods | MOD_NOREPEAT, self.vk))
        if not self.ok:
            self.error = "他のアプリに取られているかもしれません"
        self.ready.set()
        if not self.ok:
            return
        msg = MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY:
                try:
                    self.callback()
                except Exception:
                    pass
        user32.UnregisterHotKey(None, self.hk_id)

    def stop(self):
        if self._tid:
            user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)


# ---------------------------------------------------------------- キーの名前
VK_NAMES = {
    0x08: "BackSpace", 0x09: "Tab", 0x0D: "Enter", 0x10: "Shift", 0x11: "Ctrl",
    0x12: "Alt", 0x14: "CapsLock", 0x1B: "Esc", 0x20: "Space", 0x21: "PageUp",
    0x22: "PageDown", 0x23: "End", 0x24: "Home", 0x25: "←", 0x26: "↑",
    0x27: "→", 0x28: "↓", 0x2D: "Insert", 0x2E: "Delete",
    0xA0: "左Shift", 0xA1: "右Shift", 0xA2: "左Ctrl", 0xA3: "右Ctrl",
    0xA4: "左Alt", 0xA5: "右Alt",
}
for _i in range(1, 25):
    VK_NAMES[0x6F + _i] = "F%d" % _i


VK_SHIFT, VK_CONTROL, VK_MENU, VK_LWIN, VK_RWIN = 0x10, 0x11, 0x12, 0x5B, 0x5C


def mods_now():
    """いま押さえている修飾キー。RegisterHotKeyに渡す形で返す。

    tkinterのevent.stateは当てにしない。Windowsでは NumLock が
    0x0008に乗ってくるので、それをAltと読み違えて勝手にAltが入ってしまう
    （CapsLockも0x0002に乗る）。実際のキーの状態を見る。
    """
    m = 0
    if user32.GetAsyncKeyState(VK_CONTROL) & 0x8000:
        m |= MOD_CONTROL
    if user32.GetAsyncKeyState(VK_SHIFT) & 0x8000:
        m |= MOD_SHIFT
    if user32.GetAsyncKeyState(VK_MENU) & 0x8000:
        m |= MOD_ALT
    if (user32.GetAsyncKeyState(VK_LWIN) & 0x8000
            or user32.GetAsyncKeyState(VK_RWIN) & 0x8000):
        m |= MOD_WIN
    return m


def vk_name(vk):
    vk = int(vk or 0)
    if not vk:
        return "（未設定）"
    if vk in VK_NAMES:
        return VK_NAMES[vk]
    if 0x30 <= vk <= 0x5A:      # 0-9 A-Z
        return chr(vk)
    if 0x60 <= vk <= 0x69:
        return "テンキー%d" % (vk - 0x60)
    return "キー(0x%02X)" % vk


def hotkey_name(mods, vk):
    parts = []
    if mods & MOD_CONTROL:
        parts.append("Ctrl")
    if mods & MOD_SHIFT:
        parts.append("Shift")
    if mods & MOD_ALT:
        parts.append("Alt")
    if mods & MOD_WIN:
        parts.append("Win")
    parts.append(vk_name(vk))
    return "+".join(parts)
