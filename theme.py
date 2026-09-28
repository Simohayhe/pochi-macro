# -*- coding: utf-8 -*-
"""かわいい系パステルUIキット（tkinter標準のみ）。

tkinter/ttk は角丸を持たないので、カード・ボタン・バッジ・進捗バーは
Canvas に自前で描いている。
"""
from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont

# ---------------------------------------------------------------- パレット
# 3種類ある。かわいい＝パステルの明るいほう、モダン＝色を使わない落ち着いた
# 組み方、かっこいい＝暗いほう。色は全部モジュール変数なので、部品を作る前に
# use() を呼んでおくこと。
PALETTES = {
    "cute": {
        "NAME": "かわいい",
        "DARK": False,
        "BG": "#FBF7FA",       # ほんのり桜色の生成り
        "BG_SOFT": "#F4ECF4",
        "CARD": "#FFFFFF",
        "SHADOW": "#F1E5EF",
        "LINE": "#EFE6EF",
        "FIELD": "#F8F3F8",
        "INK": "#4C4457",
        "INK_SUB": "#A99CB4",
        "PINK": "#FF9BBB",     # 主役の色（かっこいい側では青になる）
        "PINK_DK": "#F4749E",
        "LAV": "#B79CF0",
        "MINT": "#68D2B0",
        "SKY": "#88C6F7",
        "LEMON": "#FFD275",
        "PEACH": "#FFAD8E",
        "RED": "#FF7B7B",
        "HOVER_SOFT": "#E8DCEA",
        "HOVER_LAV": "#9F7DE8",
        "HOVER_MINT": "#4FC3A0",
        "DANGER_BG": "#FFEDED",
        "DANGER_HOVER": "#FFD9D9",
        "ON_ACCENT": "#FFFFFF",
    },
    "modern": {
        "NAME": "モダン",
        "DARK": False,
        "FONT": "segoe",
        "RADIUS": 8,          # ボタンの角（丸ピルにしない）
        "CARD_RADIUS": 10,
        "BG": "#FAFAFA",
        "BG_SOFT": "#F1F1F3",
        "CARD": "#FFFFFF",
        "SHADOW": "#EDEDF0",
        "LINE": "#E4E4E7",
        "FIELD": "#F6F6F7",
        "INK": "#18181B",
        "INK_SUB": "#71717A",
        "PINK": "#4F46E5",     # 主役はインディゴ
        "PINK_DK": "#4338CA",
        "LAV": "#7C3AED",
        "MINT": "#059669",
        "SKY": "#0284C7",
        "LEMON": "#D97706",
        "PEACH": "#EA580C",
        "RED": "#DC2626",
        "HOVER_SOFT": "#E4E4E7",
        "HOVER_LAV": "#6D28D9",
        "HOVER_MINT": "#047857",
        "DANGER_BG": "#FEF2F2",
        "DANGER_HOVER": "#FEE2E2",
        "ON_ACCENT": "#FFFFFF",
    },
    "cool": {
        "NAME": "かっこいい",
        "DARK": True,
        "BG": "#12141A",       # 夜のコックピットみたいな暗い紺
        "BG_SOFT": "#1A1D25",
        "CARD": "#1D212B",
        "SHADOW": "#0C0E13",
        "LINE": "#2C3240",
        "FIELD": "#232936",
        "INK": "#E8ECF4",
        "INK_SUB": "#8892A6",
        "PINK": "#4C9BFF",     # 主役は青
        "PINK_DK": "#2F7FE8",
        "LAV": "#9B7BFF",
        "MINT": "#2FD6A0",
        "SKY": "#4FC8F5",
        "LEMON": "#FFC857",
        "PEACH": "#FF8F6B",
        "RED": "#FF6B6B",
        "HOVER_SOFT": "#2B3140",
        "HOVER_LAV": "#8663F0",
        "HOVER_MINT": "#22BE8C",
        "DANGER_BG": "#3A2129",
        "DANGER_HOVER": "#4A2932",
        "ON_ACCENT": "#0E1117",
    },
}
THEME = "cute"

# use() が実際の値を入れる。ここは既定（かわいい）を置いておくだけ。
BG = BG_SOFT = CARD = SHADOW = LINE = FIELD = ""
INK = INK_SUB = PINK = PINK_DK = LAV = MINT = SKY = LEMON = PEACH = RED = ""
HOVER_SOFT = HOVER_LAV = HOVER_MINT = DANGER_BG = DANGER_HOVER = ON_ACCENT = ""
RADIUS = 999          # ボタンの角の最大。999 なら高さの半分＝丸ピル
CARD_RADIUS = 20


def use(name):
    """パレットを切り替える。**部品を1つでも作る前に呼ぶこと。**

    tkinter のウィジェットは作ったときの色をそのまま抱えるので、
    あとから呼んでも画面は変わらない（アプリを起動し直す前提）。
    """
    global THEME
    pal = PALETTES.get(name) or PALETTES["cute"]
    THEME = name if name in PALETTES else "cute"
    g = globals()
    g["RADIUS"], g["CARD_RADIUS"] = 999, 20      # 指定が無ければ丸ピル
    for k, v in pal.items():
        if k not in ("NAME", "DARK", "FONT"):
            g[k] = v
    if "RoundButton" in g:
        g["RoundButton"].SCHEME = _scheme()
    return THEME


def _scheme():
    return {
        "primary": (PINK, PINK_DK, ON_ACCENT),
        "accent": (LAV, HOVER_LAV, ON_ACCENT),
        "mint": (MINT, HOVER_MINT, ON_ACCENT),
        "soft": (BG_SOFT, HOVER_SOFT, INK),
        "ghost": (CARD, BG_SOFT, INK_SUB),
        "danger": (DANGER_BG, DANGER_HOVER, RED),
    }


def dark():
    return bool((PALETTES.get(THEME) or {}).get("DARK"))


def font_kind():
    return (PALETTES.get(THEME) or {}).get("FONT") or "jp"


JP = "Yu Gothic UI"
CUTE = "UD デジタル 教科書体 NP"


def fonts():
    """使えるフォントを見て決める（無ければ Yu Gothic UI に落とす）。"""
    fams = set(tkfont.families())
    if font_kind() == "segoe":
        body = "Noto Sans JP" if "Noto Sans JP" in fams else JP
        disp = ("Segoe UI Variable Display" if "Segoe UI Variable Display" in fams
                else body)
        return {
            "ui": (body, 10), "ui_b": (body, 10, "bold"), "small": (body, 9),
            "cute": (body, 10), "cute_b": (body, 11, "bold"),
            "head": (body, 16, "bold"),
            "num": (disp, 26), "num_s": (disp, 15),
        }
    cute = CUTE if (CUTE in fams and not dark()) else JP
    return {
        "ui": (JP, 10),
        "ui_b": (JP, 10, "bold"),
        "small": (JP, 9),
        "cute": (cute, 11),
        "cute_b": (cute, 12, "bold"),
        "head": (cute, 15, "bold"),
        "num": ("Segoe UI Semibold", 26),
        "num_s": ("Segoe UI Semibold", 15),
    }


def _shade(color, k):
    """色を k 倍の明るさにする（k<1 で暗く）。"""
    c = color.lstrip("#")
    rgb = [int(c[i:i + 2], 16) for i in (0, 2, 4)]
    return "#%02X%02X%02X" % tuple(max(0, min(255, int(v * k))) for v in rgb)


def make_icon(size=64):
    """クリックの波紋のしるし。中心の点から輪が2つ広がる形。

    小さくしても「点と輪」という形が残るので、16pxのタスクバーでも
    何のアイコンか分かる。色はテーマの主役色から作るので、見た目を
    変えると一緒に変わる。
    """
    img = tk.PhotoImage(width=size, height=size)
    c = (size - 1) / 2.0
    dot_r = max(1.6, size * 0.12)
    rings = (size * 0.30, size * 0.46)
    ring_w = max(1.0, size / 12.0)
    fill = PINK
    rows, holes = [], []
    for y in range(size):
        row = []
        for x in range(size):
            dx, dy = x - c, y - c
            d = (dx * dx + dy * dy) ** 0.5
            on = d <= dot_r or any(abs(d - r) <= ring_w / 2 for r in rings)
            if on:
                row.append(fill)
            else:
                row.append(BG)
                holes.append((x, y))
        rows.append("{" + " ".join(row) + "}")
    img.put(" ".join(rows))
    for x, y in holes:
        img.transparency_set(x, y, True)
    return img


F = {}
use("cute")      # import しただけでも色が入っている状態にしておく


def init(root):
    """フォント辞書を用意し、ttk（スクロールバー等）にも色を入れる。"""
    global F
    F = fonts()
    from tkinter import ttk

    st = ttk.Style(root)
    try:
        st.theme_use("clam")
    except tk.TclError:
        pass
    st.configure("Cute.Vertical.TScrollbar", background=BG_SOFT, troughcolor=BG,
                 bordercolor=BG, arrowcolor=INK_SUB, borderwidth=0, relief="flat",
                 gripcount=0, arrowsize=12)
    st.map("Cute.Vertical.TScrollbar", background=[("active", PINK)])
    st.configure("TCombobox", arrowcolor=INK_SUB)
    root.option_add("*TCombobox*Listbox.background", FIELD)
    root.option_add("*TCombobox*Listbox.foreground", INK)
    root.option_add("*TCombobox*Listbox.selectBackground", PINK)
    root.option_add("*TCombobox*Listbox.selectForeground", ON_ACCENT)
    st.configure("Cute.Horizontal.TScale", background=CARD, troughcolor=BG_SOFT,
                 bordercolor=CARD, darkcolor=PINK, lightcolor=PINK, borderwidth=0)
    st.configure("Cute.TCombobox", fieldbackground=FIELD, background=FIELD,
                 foreground=INK, arrowcolor=INK_SUB, borderwidth=0, padding=6)
    st.map("Cute.TCombobox", fieldbackground=[("readonly", FIELD)],
           selectbackground=[("readonly", FIELD)], selectforeground=[("readonly", INK)])
    return F


# ---------------------------------------------------------------- 描画部品
def round_rect(cv, x1, y1, x2, y2, r, **kw):
    """Canvas に角丸長方形を描く（smooth ポリゴン）。"""
    r = max(0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
    pts = [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
        x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]
    return cv.create_polygon(pts, smooth=True, splinesteps=24, **kw)


class RoundButton(tk.Canvas):
    """角丸ボタン。kind: primary / soft / ghost / danger"""

    SCHEME = {}      # use() が入れる

    def __init__(self, master, text, command=None, kind="soft", bg=None,
                 font=None, padx=16, pady=8, radius=None, width=None):
        bg = BG if bg is None else bg
        self.font = font or F.get("cute", (JP, 11))
        fo = tkfont.Font(font=self.font)
        w = width or (fo.measure(text) + padx * 2)
        h = fo.metrics("linespace") + pady * 2
        super().__init__(master, width=w, height=h, bg=bg, highlightthickness=0, bd=0)
        self.command = command
        self.fill, self.hover, self.fg = self.SCHEME.get(kind, self.SCHEME["soft"])
        r = radius if radius is not None else min(h / 2, RADIUS)
        self.shape = round_rect(self, 1, 1, w - 1, h - 1, r, fill=self.fill, outline="")
        self.label = self.create_text(w / 2, h / 2 + 1, text=text, fill=self.fg,
                                      font=self.font)
        self.bind("<Enter>", lambda e: self.itemconfigure(self.shape, fill=self.hover))
        self.bind("<Leave>", lambda e: self.itemconfigure(self.shape, fill=self.fill))
        self.bind("<Button-1>", lambda e: self.itemconfigure(self.shape, fill=self.hover))
        self.bind("<ButtonRelease-1>", self._click)
        self.configure(cursor="hand2")

    def _click(self, _e=None):
        self.itemconfigure(self.shape, fill=self.fill)
        if self.command:
            self.command()

    def set_text(self, text):
        self.itemconfigure(self.label, text=text)


class PillBadge(tk.Canvas):
    """小さな角丸ピル（絵文字＋名前）"""

    def __init__(self, master, text, color, bg=None, font=None, padx=12, pady=4):
        bg = CARD if bg is None else bg
        self.font = font or F.get("small", (JP, 9))
        fo = tkfont.Font(font=self.font)
        w = fo.measure(text) + padx * 2
        h = fo.metrics("linespace") + pady * 2
        super().__init__(master, width=w, height=h, bg=bg, highlightthickness=0, bd=0)
        round_rect(self, 0, 0, w, h, min(h / 2, RADIUS), fill=color, outline="")
        self.create_text(w / 2, h / 2 + 1, text=text, fill=ON_ACCENT,
                         font=self.font)


class RoundProgress(tk.Canvas):
    """角丸の進捗バー"""

    def __init__(self, master, bg=None, color=None, height=10, track=None):
        bg, color, track = (CARD if bg is None else bg,
                            PINK if color is None else color,
                            BG_SOFT if track is None else track)
        super().__init__(master, height=height, bg=bg, highlightthickness=0, bd=0)
        self.color = color
        self.track = track
        self.h = height
        self.value = 0.0
        self.bind("<Configure>", lambda e: self._draw())

    def set(self, value, color=None):
        self.value = max(0.0, min(1.0, value))
        if color and color != self.color:
            self.color = color
        self._draw()

    def _draw(self):
        self.delete("all")
        w = self.winfo_width()
        h = self.h
        if w < 4:
            return
        round_rect(self, 0, 0, w, h, h / 2, fill=self.track, outline="")
        fw = self.value * w
        if fw > 1:
            round_rect(self, 0, 0, max(fw, h), h, h / 2, fill=self.color, outline="")


class RoundSlider(tk.Canvas):
    """まるいつまみのスライダー（0.0〜1.0）"""

    def __init__(self, master, value=0.7, command=None, bg=None, color=None,
                 height=26, track_h=8, knob_r=9):
        super().__init__(master, height=height, bg=bg, highlightthickness=0, bd=0)
        self.value = max(0.0, min(1.0, value))
        self.command = command
        self.color = color
        self.track_h = track_h
        self.knob_r = knob_r
        self.h = height
        self.bind("<Configure>", lambda e: self._draw())
        for seq in ("<Button-1>", "<B1-Motion>"):
            self.bind(seq, self._from_event)
        self.configure(cursor="hand2")

    def _from_event(self, e):
        w = self.winfo_width()
        span = max(1, w - self.knob_r * 2)
        self.set((e.x - self.knob_r) / span)
        if self.command:
            self.command(self.value)

    def set(self, v):
        self.value = max(0.0, min(1.0, v))
        self._draw()

    def _draw(self):
        self.delete("all")
        w = self.winfo_width()
        if w < 8:
            return
        cy = self.h / 2
        r = self.knob_r
        th_ = self.track_h
        round_rect(self, r, cy - th_ / 2, w - r, cy + th_ / 2, th_ / 2,
                   fill=BG_SOFT, outline="")
        x = r + (w - r * 2) * self.value
        if x > r + 1:
            round_rect(self, r, cy - th_ / 2, x, cy + th_ / 2, th_ / 2,
                       fill=self.color, outline="")
        self.create_oval(x - r, cy - r, x + r, cy + r, fill=CARD,
                         outline=self.color, width=3)


class Card(tk.Canvas):
    """白い角丸カード。中身は self.body（普通のFrame）に入れる。"""

    PAD = 14

    def __init__(self, master, bg=None, card=None, radius=None, pad=None):
        bg, card = BG if bg is None else bg, CARD if card is None else card
        radius = CARD_RADIUS if radius is None else radius
        super().__init__(master, bg=bg, highlightthickness=0, bd=0, height=60)
        self.card_color = card
        self.radius = radius
        self.pad = self.PAD if pad is None else pad
        self.body = tk.Frame(self, bg=card)
        self._item = self.create_window(self.pad, self.pad, window=self.body, anchor="nw")
        self.bind("<Configure>", self._on_conf)
        self.body.bind("<Configure>", self._on_body)

    def _on_body(self, e):
        want = e.height + self.pad * 2
        if abs(int(self["height"]) - want) > 1:
            self.configure(height=want)

    def _on_conf(self, e):
        w, h = e.width, e.height
        self.delete("bgshape")
        round_rect(self, 4, 6, w - 4, h - 1, self.radius, fill=SHADOW,
                   outline="", tags="bgshape")
        round_rect(self, 4, 2, w - 4, h - 5, self.radius, fill=self.card_color,
                   outline="", tags="bgshape")
        self.tag_lower("bgshape")
        self.itemconfigure(self._item, width=max(1, w - self.pad * 2))


def soft_entry(master, textvariable=None, width=None, font=None, bg=None, **kw):
    """やわらかい見た目の入力欄"""
    bg = CARD if bg is None else bg
    e = tk.Entry(master, textvariable=textvariable, relief="flat", bd=0,
                 bg=FIELD, fg=INK, insertbackground=PINK_DK,
                 font=font or F.get("ui", (JP, 10)),
                 highlightthickness=2, highlightbackground=LINE, highlightcolor=PINK,
                 **({"width": width} if width else {}), **kw)
    return e


def label(master, text, bg=None, fg=None, font=None, **kw):
    bg = CARD if bg is None else bg
    return tk.Label(master, text=text, bg=bg, fg=fg or INK,
                    font=font or F.get("ui", (JP, 10)), **kw)


class Chip(tk.Canvas):
    """小さな丸いショートカット"""

    def __init__(self, master, text, command, bg=None, fill=None, fg=None, font=None,
                 padx=13, pady=6):
        bg = BG if bg is None else bg
        fill = CARD if fill is None else fill
        fg = INK if fg is None else fg
        self.font = font or F.get("small", (JP, 9))
        fo = tkfont.Font(font=self.font)
        w = fo.measure(text) + padx * 2
        h = fo.metrics("linespace") + pady * 2
        super().__init__(master, width=w, height=h, bg=bg, highlightthickness=0, bd=0)
        self.command = command
        self.fill = fill
        self.shape = round_rect(self, 1, 1, w - 1, h - 1, min(h / 2, RADIUS), fill=fill,
                                outline=LINE, width=1)
        self.create_text(w / 2, h / 2 + 1, text=text, fill=fg, font=self.font)
        self.bind("<Enter>", lambda e: self.itemconfigure(self.shape,
                                                           fill=HOVER_SOFT))
        self.bind("<Leave>", lambda e: self.itemconfigure(self.shape, fill=self.fill))
        self.bind("<ButtonRelease-1>", lambda e: command())
        self.configure(cursor="hand2")
