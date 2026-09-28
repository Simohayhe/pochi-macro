# -*- coding: utf-8 -*-
"""ポチマクロ — マウス/キーボードの操作を記録・繰り返し実行するマクロツール

・一連の操作（クリック・キー、長さの上限なし）を記録して、そのまま繰り返し実行
・押す場所を画面座標で登録可能（卵の孵化のように決まった場所を押しつづける用途）
・マクロを複数保存して切り替え
・グローバルホットキーで入切（記録の開始/終了もホットキーから）
・GitHub Releasesからのアプリ内更新

    python pochi_macro.py

設定: %APPDATA%\\PochiMacro\\config.json
"""
from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import threading
import time
import uuid
import webbrowser

import tkinter as tk
from tkinter import ttk, messagebox

import macro_engine as macro
import theme as th
import updater
import winapi as wa

APP_NAME = "ポチマクロ"
APP_NAME_EN = "PochiMacro"
APP_VERSION = "0.3.0"


def _res_dir():
    base = getattr(sys, "_MEIPASS", None)
    return base or os.path.dirname(os.path.abspath(__file__))


HERE = _res_dir()
STATE_DIR = os.path.join(
    os.environ.get("APPDATA") or os.path.expanduser("~"), "PochiMacro")
CONFIG_PATH = os.path.join(STATE_DIR, "config.json")


def new_profile(name="マクロ1"):
    return {
        "id": uuid.uuid4().hex[:8],
        "name": name,
        "steps": [],
        "interval_ms": 100,
        "hold_ms": 20,
        "hold_delay_ms": 300,
        "limit": 0,
        "target": "",
        "only_target": True,
        "send_mode": macro.DEFAULT_SEND_MODE,
        "cancel_rclick": True,
    }


DEFAULT_CONFIG = {
    "theme": "cute",
    "always_on_top": False,
    "profiles": [],
    "active_profile": "",
    "hotkey_hold_on": True, "hotkey_hold_mods": macro.MOD_CONTROL, "hotkey_hold_vk": 0x52,
    "hotkey_always_on": True, "hotkey_always_mods": macro.MOD_CONTROL, "hotkey_always_vk": 0x54,
    "hotkey_press_on": True, "hotkey_press_mods": macro.MOD_CONTROL, "hotkey_press_vk": 0x4B,
    "hotkey_switch_on": True,
    "hotkey_switch_mods": macro.MOD_CONTROL | macro.MOD_SHIFT, "hotkey_switch_vk": 0x50,
    "hotkey_record_on": True,
    "hotkey_record_mods": macro.MOD_CONTROL | macro.MOD_SHIFT, "hotkey_record_vk": 0x45,
    "geometry": "780x760",
}


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return dict(default) if isinstance(default, dict) else default


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


# ======================================================================
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.cfg = dict(DEFAULT_CONFIG)
        loaded = load_json(CONFIG_PATH, {})
        self.cfg.update(loaded)
        self.cfg["profiles"] = loaded.get("profiles") or []
        if not self.cfg["profiles"]:
            self.cfg["profiles"] = [new_profile("マクロ1")]
        if not any(p["id"] == self.cfg.get("active_profile")
                   for p in self.cfg["profiles"]):
            self.cfg["active_profile"] = self.cfg["profiles"][0]["id"]

        self.macro = None            # 実行中のRunner
        self.holder = None           # 長押し
        self.hold_watch = None       # かまえ判定用フック
        self.cancel_watch = None     # 右クリック中断の見張り
        self.recorder = None         # 操作記録中のSequenceRecorder
        self.macro_kind = macro.DEFAULT_MODE
        self.cancelled_at = 0.0
        self.hk_hold = self.hk_always = self.hk_press = self.hk_switch = None
        self.hk_record = None
        self._hk_err = {"hold": "", "always": "", "press": "", "switch": "",
                        "record": ""}
        self.update_found = None

        th.use(self.cfg.get("theme", "cute"))
        self.title(APP_NAME)
        self.geometry(self.cfg.get("geometry", "780x760"))
        self.minsize(560, 520)
        self.configure(bg=th.BG)
        self.F = th.init(self)
        try:
            self._icons = [th.make_icon(n) for n in (16, 24, 32, 48, 64)]
            self.iconphoto(True, *self._icons)
        except Exception:
            self._icons = []
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "Simohaya.PochiMacro")
        except Exception:
            pass

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.attributes("-topmost", bool(self.cfg.get("always_on_top")))
        self.apply_hotkey()
        self.after(400, self._check_update_quiet)
        self.after(200, self._tick)

    # ---------------- プロファイル ----------------
    def profiles(self):
        return self.cfg["profiles"]

    def active_profile(self):
        for p in self.cfg["profiles"]:
            if p["id"] == self.cfg.get("active_profile"):
                return p
        return self.cfg["profiles"][0]

    def set_active_profile(self, pid):
        if pid == self.cfg.get("active_profile"):
            return
        self.stop_macro()
        self.stop_hold()
        self.cfg["active_profile"] = pid
        self.save_cfg()
        self.rebuild_panel()

    def add_profile(self, name):
        p = new_profile(name)
        self.cfg["profiles"].append(p)
        self.set_active_profile(p["id"])
        return p

    def duplicate_profile(self):
        src = self.active_profile()
        p = dict(src)
        p["id"] = uuid.uuid4().hex[:8]
        p["name"] = src["name"] + " のコピー"
        p["steps"] = [dict(s) for s in src.get("steps") or []]
        self.cfg["profiles"].append(p)
        self.set_active_profile(p["id"])

    def rename_profile(self, name):
        name = (name or "").strip()
        if not name:
            return
        self.active_profile()["name"] = name
        self.save_cfg()
        self.rebuild_panel()

    def delete_profile(self):
        if len(self.cfg["profiles"]) <= 1:
            messagebox.showinfo(APP_NAME, "最後の1つは消せません")
            return
        cur = self.active_profile()
        self.stop_macro()
        self.stop_hold()
        self.cfg["profiles"] = [p for p in self.cfg["profiles"] if p is not cur]
        self.cfg["active_profile"] = self.cfg["profiles"][0]["id"]
        self.save_cfg()
        self.rebuild_panel()

    def switch_to_next_profile(self):
        """ホットキーからも呼べる。動いていたら止めてから次へ。"""
        ps = self.cfg["profiles"]
        if len(ps) < 2:
            return
        idx = next((i for i, p in enumerate(ps)
                   if p["id"] == self.cfg.get("active_profile")), 0)
        self.set_active_profile(ps[(idx + 1) % len(ps)]["id"])

    # ---------------- マクロ実行 ----------------
    def _macro_cfg(self):
        p = self.active_profile()
        return {
            "steps": p.get("steps") or [],
            "interval_ms": p.get("interval_ms", 100),
            "hold_ms": p.get("hold_ms", 20),
            "limit": p.get("limit", 0),
            "target": p.get("target") or "",
            "only_target": p.get("only_target", True),
            "send_mode": p.get("send_mode") or macro.DEFAULT_SEND_MODE,
        }

    def hold_delay(self):
        try:
            return max(0.0, float(self.active_profile().get(
                "hold_delay_ms", 300)) / 1000.0)
        except (TypeError, ValueError):
            return 0.3

    def macro_running(self):
        return self.macro is not None and self.macro.is_alive()

    def macro_mode(self):
        return self.macro_kind

    def macro_ready(self):
        for st in macro.steps_of(self._macro_cfg()):
            if st.get("action") == "key" and not st.get("key_vk"):
                return False
        return True

    def macro_what(self, first=False):
        got = []
        for st in macro.steps_of(self._macro_cfg()):
            if first and got:
                break
            act = st.get("action")
            got.append(macro.vk_name(st.get("key_vk") or 0) if act == "key"
                       else macro.action_label(act))
        return " → ".join(got) if got else "?"

    def _game_in_front(self):
        p = self.active_profile()
        if not p.get("only_target", True):
            return True
        try:
            return wa.matches(p.get("target") or "")
        except Exception:
            return True

    def toggle_macro(self, mode="hold"):
        if self.macro_running():
            same = self.macro_kind == mode
            self.stop_macro()
            if same:
                return
        if not self.macro_ready():
            messagebox.showinfo(APP_NAME, "さきに送るキーを決めてください")
            return
        gate = None
        if mode == "hold":
            w = macro.HoldWatch("left", guard=self._game_in_front)
            w.start()
            w.ready.wait(0.5)
            if not w.ok:
                return
            self.hold_watch = w
            gate = lambda: w.held_for() >= self.hold_delay()
        self.stop_hold()
        self.macro_kind = mode
        self.macro = macro.Runner(self._macro_cfg, gate=gate)
        self.macro.start()
        self.sync_cancel_watch()

    def holder_running(self):
        return self.holder is not None and self.holder.is_alive()

    def toggle_hold(self):
        if self.holder_running():
            self.stop_hold()
            return
        if not self.macro_ready():
            messagebox.showinfo(APP_NAME, "さきに送るキーを決めてください")
            return
        self.stop_macro()
        self.holder = macro.Holder(self._macro_cfg)
        self.holder.start()
        self.sync_cancel_watch()

    def stop_hold(self):
        if self.holder is not None:
            self.holder.stop()
            self.holder.join(1.0)
            self.holder = None
        self.sync_cancel_watch()

    def stop_macro(self):
        if self.macro is not None:
            self.macro.stop()
            self.macro = None
        if self.hold_watch is not None:
            self.hold_watch.stop()
            self.hold_watch = None
        self.sync_cancel_watch()

    def cancel_button(self):
        act = macro.steps_of(self._macro_cfg())[0].get("action")
        return "left" if (self.macro_running() and act == "right") else "right"

    def _on_right_cancel(self):
        if not (self.macro_running() or self.holder_running()):
            return
        self.cancelled_at = time.time()
        self.stop_hold()
        self.stop_macro()

    def sync_cancel_watch(self):
        p = self.active_profile()
        want = (p.get("cancel_rclick", True)
                and (self.holder_running()
                     or (self.macro_running() and self.macro_mode() != "hold")))
        btn = self.cancel_button()
        if (self.cancel_watch is not None
                and (not want or self.cancel_watch.button != btn)):
            self.cancel_watch.stop()
            self.cancel_watch = None
        if want and self.cancel_watch is None:
            w = macro.CancelWatch(self._on_right_cancel, btn,
                                  guard=self._game_in_front)
            w.start()
            w.ready.wait(0.5)
            self.cancel_watch = w if w.ok else None

    # ---------------- ホットキー ----------------
    def _hotkey_toggle_record(self):
        """記録ホットキーはワーカースレッドから呼ばれるので、Tk操作はafterで本体へ渡す。"""
        if self.panel is not None:
            self.panel.toggle_record()

    def apply_hotkey(self):
        for which, head, on_key, hk_id, act, dflt in (
                ("hk_hold", "hotkey_hold", "hotkey_hold_on", 1,
                 lambda: self.toggle_macro("hold"), 0x52),
                ("hk_always", "hotkey_always", "hotkey_always_on", 2,
                 lambda: self.toggle_macro("always"), 0x54),
                ("hk_press", "hotkey_press", "hotkey_press_on", 3,
                 self.toggle_hold, 0x4B),
                ("hk_switch", "hotkey_switch", "hotkey_switch_on", 4,
                 self.switch_to_next_profile, 0x50),
                ("hk_record", "hotkey_record", "hotkey_record_on", 5,
                 lambda: self.after(0, self._hotkey_toggle_record), 0x45)):
            old = getattr(self, which)
            if old is not None:
                old.stop()
            setattr(self, which, None)
            key = which[3:]
            self._hk_err[key] = ""
            if not self.cfg.get(on_key, True):
                continue
            hk = macro.Hotkey(self.cfg.get(head + "_mods", macro.MOD_CONTROL),
                              self.cfg.get(head + "_vk", dflt), act, hk_id=hk_id)
            hk.start()
            hk.ready.wait(1.0)
            if hk.ok:
                setattr(self, which, hk)
            else:
                self._hk_err[key] = hk.error or "登録できませんでした"

    def hotkey_status(self, which):
        head = {"hold": "hotkey_hold", "always": "hotkey_always",
               "press": "hotkey_press", "switch": "hotkey_switch",
               "record": "hotkey_record"}[which]
        dflt = {"hold": 0x52, "always": 0x54, "press": 0x4B, "switch": 0x50,
               "record": 0x45}[which]
        on = self.cfg.get(head + "_on", True)
        name = macro.hotkey_name(self.cfg.get(head + "_mods", macro.MOD_CONTROL),
                                 self.cfg.get(head + "_vk", dflt))
        what = {"hold": "押しっぱなしで実行", "always": "ずっと実行",
               "press": "長押し", "switch": "次のマクロへ切替",
               "record": "操作の記録を開始/終了"}[which]
        if not on:
            return "%s のショートカットは使いません" % what, name
        err = self._hk_err.get(which)
        if err:
            return "⚠ %s が使えません（%s）" % (name, err), name
        return "%s … %s をどこからでも入切" % (name, what), name

    # ---------------- 更新確認 ----------------
    def _check_update_quiet(self):
        def go():
            info = updater.check(timeout=8)
            if info.get("ok") and updater.is_newer(info["tag"], APP_VERSION):
                self.update_found = info
                self.after(0, self._mark_update_button)
        threading.Thread(target=go, daemon=True).start()

    def _mark_update_button(self):
        if self.update_found:
            self.btn_update.set_text("⬆ 更新あり")

    def open_update(self):
        UpdateDialog(self)

    # ---------------- 設定 ----------------
    def open_settings(self):
        SettingsDialog(self)

    # ---------------- 画面 ----------------
    def _build_ui(self):
        F = self.F
        pad = 16
        head = tk.Frame(self, bg=th.BG)
        head.pack(fill="x", padx=pad, pady=(14, 0))
        tk.Label(head, text=APP_NAME, bg=th.BG, fg=th.INK,
                 font=F["head"]).pack(side="left")
        tk.Label(head, text="  v%s" % APP_VERSION, bg=th.BG, fg=th.INK_SUB,
                 font=F["small"]).pack(side="left", anchor="s", pady=(0, 4))
        ctrl = tk.Frame(head, bg=th.BG)
        ctrl.pack(side="right")
        th.RoundButton(ctrl, "⚙ 設定", self.open_settings, kind="soft",
                       bg=th.BG, font=F["small"]).pack(side="right", padx=(6, 0))
        self.btn_update = th.RoundButton(ctrl, "⬆ 更新", self.open_update,
                                         kind="soft", bg=th.BG, font=F["small"],
                                         width=110)
        self.btn_update.pack(side="right", padx=6)

        # ---- プロファイル行 ----
        prow = th.Card(self, bg=th.BG)
        prow.pack(fill="x", padx=pad, pady=(10, 0))
        b = prow.body
        tk.Label(b, text="マクロ", bg=th.CARD, fg=th.INK, font=F["cute_b"],
                 width=6, anchor="w").pack(side="left")
        self.v_profile = tk.StringVar()
        self.cb_profile = ttk.Combobox(b, textvariable=self.v_profile,
                                       state="readonly", width=22,
                                       style="Cute.TCombobox", font=F["ui"])
        self.cb_profile.pack(side="left", padx=(0, 6))
        self.cb_profile.bind("<<ComboboxSelected>>", self._on_pick_profile)
        th.RoundButton(b, "＋新規", self._new_profile_dialog, kind="soft",
                       bg=th.CARD, font=F["small"], padx=10,
                       pady=5).pack(side="left", padx=2)
        th.RoundButton(b, "複製", self.duplicate_profile, kind="soft",
                       bg=th.CARD, font=F["small"], padx=10,
                       pady=5).pack(side="left", padx=2)
        th.RoundButton(b, "名前を変える", self._rename_profile_dialog, kind="soft",
                       bg=th.CARD, font=F["small"], padx=10,
                       pady=5).pack(side="left", padx=2)
        th.RoundButton(b, "削除", self.delete_profile, kind="danger",
                       bg=th.CARD, font=F["small"], padx=10,
                       pady=5).pack(side="left", padx=2)

        self.panel_holder = tk.Frame(self, bg=th.BG)
        self.panel_holder.pack(fill="both", expand=True, padx=pad, pady=(10, pad))
        self.panel = None
        self.rebuild_panel()

    def _refresh_profile_combo(self):
        ps = self.profiles()
        self.cb_profile["values"] = [p["name"] for p in ps]
        self.v_profile.set(self.active_profile()["name"])

    def _on_pick_profile(self, _e=None):
        idx = self.cb_profile.current()
        if 0 <= idx < len(self.profiles()):
            self.set_active_profile(self.profiles()[idx]["id"])

    def _new_profile_dialog(self):
        name = _ask_text(self, "新しいマクロ", "名前", "マクロ%d" % (len(self.profiles()) + 1))
        if name:
            self.add_profile(name)

    def _rename_profile_dialog(self):
        name = _ask_text(self, "名前を変える", "名前", self.active_profile()["name"])
        if name:
            self.rename_profile(name)

    def rebuild_panel(self):
        if self.panel is not None:
            self.panel.destroy()
        self._refresh_profile_combo()
        self.panel = MacroPanel(self.panel_holder, self)
        self.panel.pack(fill="both", expand=True)

    def _tick(self):
        if self.panel is not None and self.panel.winfo_exists():
            self.panel.update_view()
        self.after(200, self._tick)

    # ---------------- 終了 ----------------
    def save_cfg(self):
        try:
            self.cfg["geometry"] = self.winfo_geometry()
        except Exception:
            pass
        save_json(CONFIG_PATH, self.cfg)

    def restart(self):
        """設定を保存して、自分を起動し直す（テーマ変更の反映用）。"""
        self.save_cfg()
        if getattr(sys, "frozen", False):
            args = [sys.executable]
        else:
            args = [sys.executable, os.path.abspath(sys.argv[0])]
        try:
            subprocess.Popen(args, cwd=os.path.dirname(args[-1]) or None,
                             close_fds=True)
        except OSError:
            return False
        self.on_close()
        return True

    def on_close(self):
        self.save_cfg()
        self.stop_hold()
        self.stop_macro()
        if self.recorder is not None:
            self.recorder.stop()
        if self.cancel_watch is not None:
            self.cancel_watch.stop()
        for hk in (self.hk_hold, self.hk_always, self.hk_press, self.hk_switch,
                  self.hk_record):
            if hk is not None:
                hk.stop()
        self.destroy()


def _ask_text(parent, title, label, initial=""):
    top = tk.Toplevel(parent)
    top.title(title)
    top.configure(bg=th.BG)
    top.transient(parent)
    top.grab_set()
    tk.Label(top, text=label, bg=th.BG, fg=th.INK,
             font=parent.F["cute"]).pack(padx=16, pady=(14, 4), anchor="w")
    v = tk.StringVar(value=initial)
    e = th.soft_entry(top, v, width=28)
    e.pack(padx=16, ipady=4)
    e.focus_set()
    e.select_range(0, "end")
    got = {"v": None}

    def ok(_e=None):
        got["v"] = v.get().strip()
        top.destroy()

    def cancel(_e=None):
        top.destroy()

    btn = tk.Frame(top, bg=th.BG)
    btn.pack(fill="x", padx=16, pady=14)
    th.RoundButton(btn, "OK", ok, kind="primary", bg=th.BG,
                   font=parent.F["cute"]).pack(side="right")
    th.RoundButton(btn, "キャンセル", cancel, kind="soft", bg=th.BG,
                   font=parent.F["cute"]).pack(side="right", padx=6)
    e.bind("<Return>", ok)
    e.bind("<Escape>", cancel)
    top.wait_window()
    return got["v"]


# ======================================================================
class MacroPanel(tk.Frame):
    """マクロの中身（ステップ・間隔・対象・送り方・ホットキー）の画面。"""

    def __init__(self, master, app: App):
        super().__init__(master, bg=th.BG)
        self.app = app
        self.F = app.F
        self._capturing = False
        self._live_job = None
        F = app.F
        p = app.active_profile()

        self.canvas = tk.Canvas(self, bg=th.BG, highlightthickness=0, bd=0)
        vs = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview,
                           style="Cute.Vertical.TScrollbar")
        self.canvas.configure(yscrollcommand=vs.set)
        vs.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner = tk.Frame(self.canvas, bg=th.BG)
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(
            scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(
            self._win, width=e.width))
        self.canvas.bind("<MouseWheel>", self._wheel)
        self.inner.bind("<MouseWheel>", self._wheel)

        # ---- 上: スイッチと状態 ----
        top = th.Card(self.inner, bg=th.BG)
        top.pack(fill="x")
        b = top.body
        row = tk.Frame(b, bg=th.CARD)
        row.pack(fill="x")
        self.btn = th.RoundButton(row, "▶ かまえる", lambda: self.toggle("hold"),
                                  kind="primary", bg=th.CARD, font=F["cute_b"], padx=20)
        self.btn.pack(side="left")
        self.btn_always = th.RoundButton(row, "▶ ずっと実行",
                                         lambda: self.toggle("always"), kind="accent",
                                         bg=th.CARD, font=F["cute_b"], padx=20)
        self.btn_always.pack(side="left", padx=8)
        self.btn_press = th.RoundButton(row, "⬇ 長押し", self.toggle_hold,
                                        kind="soft", bg=th.CARD, font=F["cute_b"],
                                        padx=20)
        self.btn_press.pack(side="left")
        self.lbl_state = tk.Label(row, text="", bg=th.CARD, fg=th.INK,
                                  font=F["cute"], anchor="w")
        self.lbl_state.pack(side="left", padx=14)
        self.lbl_sub = tk.Label(b, text="", bg=th.CARD, fg=th.INK_SUB,
                                font=F["small"], anchor="w", justify="left")
        self.lbl_sub.pack(fill="x", pady=(6, 0))

        # ---- 操作の設定 ----
        conf = th.Card(self.inner, bg=th.BG)
        conf.pack(fill="x", pady=(8, 0))
        c = conf.body

        tk.Label(c, text="一連の操作", bg=th.CARD, fg=th.INK,
                 font=F["cute_b"]).pack(anchor="w", pady=(0, 4))

        # ---- 場所を順番に教える（クリック検知に頼らない・いちばん確実）----
        trow = tk.Frame(c, bg=th.CARD)
        trow.pack(fill="x", pady=(0, 2))
        self.btn_teach = th.RoundButton(trow, "🖱 場所を順番に教える",
                                        self.toggle_teach, kind="primary",
                                        bg=th.CARD, font=F["small"], padx=12,
                                        pady=6)
        self.btn_teach.pack(side="left")
        tk.Label(trow, text="待つ秒数", bg=th.CARD, fg=th.INK_SUB,
                 font=F["small"]).pack(side="left", padx=(10, 2))
        self.v_teach_delay = tk.StringVar(value="3")
        th.soft_entry(trow, self.v_teach_delay, width=3).pack(side="left", ipady=3)
        self.lbl_teach = tk.Label(c, text="対象のアプリへ行って、①の場所にマウスを"
                                        "置いたまま数秒待つと覚えます。次の場所へ"
                                        "動かせば②、③…と続けて覚えられます"
                                        "（クリックする必要はありません）",
                                  bg=th.CARD, fg=th.INK_SUB, font=F["small"],
                                  wraplength=740, justify="left")
        self.lbl_teach.pack(anchor="w", pady=(2, 8))
        self._teach = None

        rrow = tk.Frame(c, bg=th.CARD)
        rrow.pack(fill="x", pady=(0, 4))
        self.btn_record = th.RoundButton(rrow, "⏺ 操作を記録", self.toggle_record,
                                         kind="soft", bg=th.CARD, font=F["small"],
                                         padx=12, pady=6)
        self.btn_record.pack(side="left")
        th.RoundButton(rrow, "＋ 手で追加", self.add_step, kind="soft",
                       bg=th.CARD, font=F["small"], padx=10,
                       pady=6).pack(side="left", padx=6)
        th.RoundButton(rrow, "▶ ためす", self.test_once, kind="soft",
                       bg=th.CARD, font=F["small"], padx=10,
                       pady=6).pack(side="left", padx=6)
        tk.Label(c, text="⏺ 操作を記録 はクリック／キー入力をそのまま拾いますが、"
                        "ゲームによっては（とくに最前面にしたとき）拾えないこと"
                        "があります。そのときは上の「場所を順番に教える」を"
                        "使ってください",
                 bg=th.CARD, fg=th.INK_SUB, font=F["small"], wraplength=740,
                 justify="left").pack(anchor="w", pady=(0, 2))
        self.lbl_record = tk.Label(c, text="", bg=th.CARD, fg=th.INK_SUB,
                                   font=F["small"], wraplength=740, justify="left")
        self.lbl_record.pack(anchor="w", pady=(0, 6))

        self.steps_frame = tk.Frame(c, bg=th.CARD)
        self.steps_frame.pack(fill="x", pady=(0, 8))
        self.step_rows = []
        self._rebuild_steps_ui()

        nrow = tk.Frame(c, bg=th.CARD)
        nrow.pack(fill="x", pady=(2, 4))
        tk.Label(nrow, text="間隔", bg=th.CARD, fg=th.INK, font=F["cute"],
                 anchor="w").pack(side="left")
        self.v_interval = tk.StringVar(
            value=macro.fmt_secs(float(p.get("interval_ms") or 100) / 1000.0))
        th.soft_entry(nrow, self.v_interval, width=7).pack(side="left", padx=(4, 2),
                                                            ipady=3)
        for txt, ms in (("0.1", 100), ("0.5", 500), ("1秒", 1000), ("5秒", 5000)):
            th.Chip(nrow, txt, lambda v=ms: self._set_interval(v), bg=th.CARD,
                    font=F["small"]).pack(side="left", padx=2)
        tk.Label(nrow, text="  回数", bg=th.CARD, fg=th.INK, font=F["cute"],
                 anchor="w").pack(side="left", padx=(12, 0))
        self.v_limit = tk.StringVar(value=str(int(p.get("limit") or 0)))
        th.soft_entry(nrow, self.v_limit, width=5).pack(side="left", padx=4, ipady=3)
        tk.Label(nrow, text="（0=ずっと）", bg=th.CARD, fg=th.INK_SUB,
                 font=F["small"]).pack(side="left")

        # ---- 詳細設定（ふだんは隠す） ----
        self.v_hold = tk.StringVar(value=str(int(p.get("hold_ms") or 20)))
        self.v_delay = tk.StringVar(
            value="%g" % (float(p.get("hold_delay_ms", 300)) / 1000.0))
        self.v_target = tk.StringVar(value=p.get("target") or "")
        self.v_send = tk.StringVar(value=p.get("send_mode") or macro.DEFAULT_SEND_MODE)
        self.v_rcancel = tk.BooleanVar(value=bool(p.get("cancel_rclick", True)))
        self.v_only = tk.BooleanVar(value=bool(p.get("only_target", True)))

        self._adv_open = False
        self.btn_adv = th.RoundButton(c, "▾ 詳細設定", self.toggle_adv, kind="ghost",
                                      bg=th.CARD, font=F["small"], padx=8, pady=4)
        self.btn_adv.pack(anchor="w", pady=(6, 0))
        self.adv = tk.Frame(c, bg=th.CARD)

        a1 = tk.Frame(self.adv, bg=th.CARD)
        a1.pack(fill="x", pady=(8, 2))
        tk.Label(a1, text="対象アプリ", bg=th.CARD, fg=th.INK, font=F["small"],
                 width=9, anchor="w").pack(side="left")
        th.soft_entry(a1, self.v_target, width=20).pack(side="left", ipady=3)
        th.RoundButton(a1, "最前面のを使う", self.pick_foreground, kind="soft",
                       bg=th.CARD, font=F["small"], padx=10,
                       pady=4).pack(side="left", padx=6)
        self.lbl_found = tk.Label(a1, text="", bg=th.CARD, fg=th.INK_SUB,
                                  font=F["small"])
        self.lbl_found.pack(side="left")

        self.chk_only = tk.Checkbutton(
            self.adv, text="このアプリが最前面のときだけ動かす（おすすめ）",
            variable=self.v_only, command=self.save, bg=th.CARD, fg=th.INK,
            activebackground=th.CARD, activeforeground=th.INK, selectcolor=th.FIELD,
            font=F["small"], bd=0, highlightthickness=0, anchor="w")
        self.chk_only.pack(anchor="w", pady=(2, 6))

        a2 = tk.Frame(self.adv, bg=th.CARD)
        a2.pack(fill="x", pady=2)
        tk.Label(a2, text="押す長さ", bg=th.CARD, fg=th.INK, font=F["small"],
                 width=9, anchor="w").pack(side="left")
        th.soft_entry(a2, self.v_hold, width=6).pack(side="left", ipady=3)
        tk.Label(a2, text="ミリ秒　長押し判定", bg=th.CARD, fg=th.INK,
                 font=F["small"]).pack(side="left", padx=(10, 4))
        th.soft_entry(a2, self.v_delay, width=5).pack(side="left", ipady=3)
        tk.Label(a2, text="秒", bg=th.CARD, fg=th.INK, font=F["small"]).pack(
            side="left")

        tk.Label(self.adv, text="送り方", bg=th.CARD, fg=th.INK, font=F["small"],
                 anchor="w").pack(anchor="w", pady=(8, 0))
        for key, lbl in macro.SEND_MODES:
            tk.Radiobutton(self.adv, text=lbl, variable=self.v_send, value=key,
                           command=self.save_send, bg=th.CARD, fg=th.INK,
                           activebackground=th.CARD, activeforeground=th.INK,
                           selectcolor=th.FIELD, font=F["small"], bd=0,
                           highlightthickness=0, anchor="w").pack(anchor="w")

        self.chk_rcancel = tk.Checkbutton(
            self.adv, text="右クリックでとめる", variable=self.v_rcancel,
            command=self.save, bg=th.CARD, fg=th.INK, activebackground=th.CARD,
            activeforeground=th.INK, selectcolor=th.FIELD, font=F["small"], bd=0,
            highlightthickness=0, anchor="w")
        self.chk_rcancel.pack(anchor="w", pady=(8, 8))

        # ---- ホットキー ----
        hk = th.Card(self.inner, bg=th.BG)
        hk.pack(fill="x", pady=(8, 0))
        hb = hk.body
        tk.Label(hb, text="ショートカット", bg=th.CARD, fg=th.INK,
                 font=F["cute_b"]).pack(anchor="w", pady=(0, 4))
        self.lbl_hk = {}
        for which, title in (("hold", "かまえる"), ("always", "ずっと実行"),
                             ("press", "長押し"), ("switch", "次のマクロへ"),
                             ("record", "操作を記録")):
            row = tk.Frame(hb, bg=th.CARD)
            row.pack(fill="x", pady=2)
            tk.Label(row, text=title, bg=th.CARD, fg=th.INK, font=F["small"],
                     width=10, anchor="w").pack(side="left")
            btn = th.RoundButton(row, "", lambda w=which: self.capture_hotkey(w),
                                 kind="soft", bg=th.CARD, font=F["small"],
                                 padx=10, pady=4, width=150)
            btn.pack(side="left")
            v_on = tk.BooleanVar(value=bool(self.app.cfg.get("hotkey_%s_on" % which, True)))
            tk.Checkbutton(row, text="使う", variable=v_on,
                           command=lambda w=which, v=v_on: self.save_hotkey_on(w, v),
                           bg=th.CARD, fg=th.INK, activebackground=th.CARD,
                           activeforeground=th.INK, selectcolor=th.FIELD,
                           font=F["small"], bd=0, highlightthickness=0).pack(
                side="left", padx=8)
            lbl = tk.Label(row, text="", bg=th.CARD, fg=th.PINK_DK, font=F["small"])
            lbl.pack(side="left")
            self.lbl_hk[which] = (btn, lbl)

        self.live(self.v_interval, self.v_hold, self.v_limit, self.v_delay,
                 self.v_target)
        self.update_view()

    # ---------------- 操作ステップ（一連の操作。長さの上限は無い）----------------
    def _rebuild_steps_ui(self):
        for w in self.steps_frame.winfo_children():
            w.destroy()
        self.step_rows = []
        steps = self.app.active_profile().get("steps") or []
        if not steps:
            tk.Label(self.steps_frame, text="まだ操作がありません。"
                                            "⏺ 記録開始 で覚えさせるか、"
                                            "「＋ 手で追加」で作ってください",
                     bg=th.CARD, fg=th.INK_SUB, font=self.F["small"]).pack(anchor="w")
        for i, st in enumerate(steps):
            row = self._step_row(self.steps_frame, i, st)
            self.step_rows.append(row)
            self.live(row["gap"])

    def _step_row(self, parent, i, st):
        F = self.F
        row = tk.Frame(parent, bg=th.CARD)
        row.pack(fill="x", pady=2)
        tk.Label(row, text="%d" % (i + 1), bg=th.CARD, fg=th.INK_SUB,
                 font=F["small"], width=3, anchor="e").pack(side="left")
        v_act = tk.StringVar(
            value=macro.action_label(st.get("action") or macro.DEFAULT_ACTION))
        cb = ttk.Combobox(row, textvariable=v_act, state="readonly", width=14,
                          style="Cute.TCombobox", font=F["ui"])
        cb["values"] = [lbl for _k, lbl in macro.ACTIONS]
        cb.pack(side="left", padx=(2, 4))
        cb.bind("<<ComboboxSelected>>", lambda e: self.save())

        btn = th.RoundButton(row, "", lambda n=i: self.capture_key(n), kind="soft",
                             bg=th.CARD, font=F["small"], padx=8, pady=4, width=130)
        btn.pack(side="left", padx=2)

        btn_pos = th.RoundButton(row, "", lambda n=i: self.capture_pos(n),
                                 kind="ghost", bg=th.CARD, font=F["small"],
                                 padx=8, pady=4, width=120)
        btn_pos.pack(side="left", padx=2)
        th.RoundButton(row, "解除", lambda n=i: self.clear_pos(n), kind="ghost",
                       bg=th.CARD, font=F["small"], padx=6, pady=4).pack(
            side="left", padx=2)

        tk.Label(row, text="間", bg=th.CARD, fg=th.INK_SUB, font=F["small"]).pack(
            side="left", padx=(6, 0))
        v_gap = tk.StringVar(value=macro.fmt_secs(float(st.get("gap_ms", 120)) / 1000.0))
        e = th.soft_entry(row, v_gap, width=6)
        e.pack(side="left", padx=2, ipady=3)
        e.bind("<FocusOut>", lambda ev: self.save())

        th.RoundButton(row, "✕", lambda n=i: self.delete_step(n), kind="danger",
                       bg=th.CARD, font=F["small"], padx=6, pady=4).pack(
            side="left", padx=(6, 0))
        return {"act": v_act, "cb": cb, "btn": btn, "btn_pos": btn_pos, "gap": v_gap,
                "vk": int(st.get("key_vk") or 0), "scan": int(st.get("key_scan") or 0),
                "pos": list(st["pos"]) if st.get("pos") else None}

    def add_step(self):
        self.save()
        p = self.app.active_profile()
        p.setdefault("steps", []).append(
            {"action": macro.DEFAULT_ACTION, "gap_ms": 300, "key_vk": 0,
             "key_scan": 0, "pos": None})
        self.app.save_cfg()
        self._rebuild_steps_ui()
        self.update_view()

    def delete_step(self, i):
        self.save()
        steps = self.app.active_profile().get("steps") or []
        if 0 <= i < len(steps):
            del steps[i]
        self.app.save_cfg()
        self._rebuild_steps_ui()
        self.update_view()

    def step_name(self, i):
        want = self.step_rows[i]["act"].get()
        for k, lbl in macro.ACTIONS:
            if lbl == want:
                return k
        return macro.DEFAULT_ACTION

    def _int(self, var, default, lo, hi):
        try:
            return max(lo, min(hi, int(float(var.get()))))
        except ValueError:
            return default

    def _set_interval(self, ms):
        self.v_interval.set(macro.fmt_secs(ms / 1000.0))

    def toggle_adv(self):
        self._adv_open = not self._adv_open
        if self._adv_open:
            self.adv.pack(fill="x")
            self.btn_adv.set_text("▴ 詳細設定")
        else:
            self.adv.pack_forget()
            self.btn_adv.set_text("▾ 詳細設定")

    def live(self, *vars_):
        for v in vars_:
            v.trace_add("write", lambda *a: self._live_soon())

    def _live_soon(self):
        if self._live_job is not None:
            try:
                self.after_cancel(self._live_job)
            except Exception:
                pass
        self._live_job = self.after(450, self._live_now)

    def _live_now(self):
        self._live_job = None
        if self._capturing:
            return
        self.save()

    def _secs_ms(self, var, current_ms, lo_ms, hi_ms):
        got = macro.parse_secs(var.get(), None)
        if got is None:
            return current_ms
        return max(lo_ms, min(hi_ms, int(round(got * 1000))))

    def steps_cfg(self):
        out = []
        for i, row in enumerate(self.step_rows):
            act = self.step_name(i)
            gap = self._secs_ms(row["gap"], int(row.get("gap_ms") or 120), 0, 600000)
            row["gap_ms"] = gap
            out.append({"action": act, "key_vk": row["vk"], "key_scan": row["scan"],
                       "gap_ms": gap,
                       "pos": list(row["pos"]) if row.get("pos") else None})
        return out

    def save(self):
        p = self.app.active_profile()
        p["steps"] = self.steps_cfg()
        p["interval_ms"] = self._secs_ms(self.v_interval, p.get("interval_ms", 100),
                                         1, 3600000)
        p["hold_ms"] = self._int(self.v_hold, 20, 0, 5000)
        try:
            p["hold_delay_ms"] = max(0, min(5000, int(float(self.v_delay.get()) * 1000)))
        except (TypeError, ValueError):
            pass
        p["limit"] = self._int(self.v_limit, 0, 0, 1000000)
        p["target"] = self.v_target.get().strip()
        p["only_target"] = bool(self.v_only.get())
        p["send_mode"] = self.v_send.get()
        p["cancel_rclick"] = bool(self.v_rcancel.get())
        self.app.save_cfg()
        self.update_view()

    def save_send(self):
        self.save()
        direct = self.v_send.get() != "input"
        if direct and self.v_only.get():
            self.v_only.set(False)
            self.save()
        self.chk_only.config(state="disabled" if direct else "normal")

    def save_hotkey_on(self, which, var):
        self.app.cfg["hotkey_%s_on" % which] = bool(var.get())
        self.app.save_cfg()
        self.app.apply_hotkey()
        self.update_view()

    def pick_foreground(self):
        self.after(1500, self._pick_now)
        self.lbl_sub.config(text="1.5秒以内に対象のウィンドウをクリックしてください…")

    def _pick_now(self):
        name = wa.foreground_exe()
        if name and name.lower() != "pochimacro.exe":
            self.v_target.set(name)
        self.update_view()

    # ---------------- 押す場所 ----------------
    def capture_pos(self, i):
        if self._capturing or getattr(self, "_pos_rec", None) is not None:
            return
        self.step_rows[i]["btn_pos"].set_text("クリックしてください…")
        self._pos_target = i
        self._pos_rec = macro.PositionRecorder(1)
        self._pos_rec.start()
        self._poll_pos()

    def clear_pos(self, i):
        self.step_rows[i]["pos"] = None
        self.save()
        self.update_view()

    def _poll_pos(self):
        rec = getattr(self, "_pos_rec", None)
        if rec is None:
            return
        if rec.done:
            if rec.points:
                self.step_rows[self._pos_target]["pos"] = list(rec.points[0])
                self.save()
            self._pos_rec = None
            self.update_view()
            return
        if not rec.is_alive():
            self._pos_rec = None
            self.update_view()
            return
        self.after(80, self._poll_pos)

    # ---------------- キー取り込み ----------------
    def capture_key(self, i=0):
        self._capture("key%d" % i)

    def capture_hotkey(self, which):
        self._capture("hotkey:" + which)

    def _capture(self, what):
        if self._capturing:
            self._end_capture()
            return
        if getattr(self, "_pos_rec", None) is not None:
            return
        self._capturing = what
        if what.startswith("key"):
            btn = self.step_rows[int(what[3:])]["btn"]
        else:
            btn = self.lbl_hk[what.split(":", 1)[1]][0]
        btn.set_text("キーを押してください…（Escでやめる）")
        top = self.winfo_toplevel()
        self._bind_ids = [
            ("<KeyPress>", top.bind("<KeyPress>", self._on_capture_key, add="+")),
            ("<Alt-KeyPress>", top.bind("<Alt-KeyPress>", self._on_capture_key,
                                        add="+")),
        ]
        top.focus_force()

    def _end_capture(self):
        self._capturing = False
        top = self.winfo_toplevel()
        for seq, bid in getattr(self, "_bind_ids", []):
            try:
                top.unbind(seq, bid)
            except tk.TclError:
                pass
        self._bind_ids = []
        self.update_view()

    def _on_capture_key(self, e):
        if not self._capturing:
            return None
        vk = e.keycode
        if vk in (0x10, 0x11, 0x12, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5, 0x5B):
            return "break"
        if vk == 0x1B:
            self._end_capture()
            return "break"
        what = self._capturing
        self._end_capture()
        if what.startswith("key"):
            row = self.step_rows[int(what[3:])]
            row["vk"], row["scan"] = vk, macro.scancode_of(vk)
            self.save()
        else:
            which = what.split(":", 1)[1]
            mods = macro.mods_now() or macro.MOD_CONTROL
            self.app.cfg["hotkey_%s_mods" % which] = mods
            self.app.cfg["hotkey_%s_vk" % which] = vk
            self.app.save_cfg()
            self.app.apply_hotkey()
        self.update_view()
        return "break"

    # ---------------- 場所を順番に教える ----------------
    # クリックそのものを検知しない。対象アプリにマウスを置いて待つだけなので、
    # ⏺ 操作を記録 がアンチチート等で拾えないゲームでも確実に使える。
    def toggle_teach(self):
        if self._teach is not None:
            self._stop_teach("やめました")
            return
        if self.app.recorder is not None and self.app.recorder.is_alive():
            self.app.recorder.stop()
        self.save()
        try:
            delay = max(0.5, min(30.0, float(self.v_teach_delay.get())))
        except (TypeError, ValueError):
            delay = 3.0
        self._teach = {"n": 0, "delay": delay, "job": None}
        self.btn_teach.set_text("■ やめる")
        self._teach_arm()

    def _teach_arm(self):
        t = self._teach
        if t is None:
            return
        t["n"] += 1
        t["remain"] = t["delay"]
        self._teach_tick()

    def _teach_tick(self):
        t = self._teach
        if t is None:
            return
        if t["remain"] <= 0:
            pos = wa.cursor_pos()
            p = self.app.active_profile()
            p.setdefault("steps", []).append(
                {"action": "left", "gap_ms": 300, "key_vk": 0, "key_scan": 0,
                 "pos": list(pos)})
            self.app.save_cfg()
            self._rebuild_steps_ui()
            self.update_view()
            self.lbl_teach.config(
                text="✅ %d番目: (%d, %d) を覚えました。つづけて②③…を教えるなら"
                     "次の場所へマウスを動かしてください（終わるなら「■ やめる」）"
                     % (t["n"], pos[0], pos[1]), fg=th.MINT)
            t["job"] = self.after(900, self._teach_arm)
            return
        self.lbl_teach.config(
            text="%d番目… あと%.1f秒（その場所で待っていてください）"
                 % (t["n"], max(0.0, t["remain"])), fg=th.INK)
        t["remain"] -= 0.2
        t["job"] = self.after(200, self._teach_tick)

    def _stop_teach(self, msg):
        t = self._teach
        if t is not None and t.get("job") is not None:
            try:
                self.after_cancel(t["job"])
            except Exception:
                pass
        self._teach = None
        self.btn_teach.set_text("🖱 場所を順番に教える")
        self.lbl_teach.config(text=msg, fg=th.INK_SUB)

    # ---------------- 操作を記録する ----------------
    def toggle_record(self):
        if self._teach is not None:
            self._stop_teach("")
        if self.app.recorder is not None and self.app.recorder.is_alive():
            self.app.recorder.stop()          # 終わりはじめる。仕上げは_poll_recordで
            return
        exclude = set()
        if self.app.cfg.get("hotkey_record_on", True):
            exclude.add(self.app.cfg.get("hotkey_record_vk", 0x45))
        self.save()          # 記録で上書きする前に、今の手編集をいったん確定させる
        rec = macro.SequenceRecorder(0, exclude_vks=exclude)
        self.app.recorder = rec
        rec.start()
        self.btn_record.set_text("■ 記録終了")
        self.lbl_record.config(
            text="対象のアプリへ行って、実際に操作してください"
                 "（Esc、またはもう一度ホットキー/ボタンで終了）", fg=th.INK)
        self._poll_record()

    def _poll_record(self):
        rec = self.app.recorder
        if rec is None:
            return
        n = len(rec.steps)
        if rec.done:
            self.app.recorder = None
            self.btn_record.set_text("⏺ 記録開始")
            if n and not (rec.cancelled and n == 0):
                p = self.app.active_profile()
                p["steps"] = [dict(s) for s in rec.steps]
                self.app.save_cfg()
                self._rebuild_steps_ui()
                self.lbl_record.config(text="✅ %d個の操作を記録しました" % n,
                                       fg=th.MINT)
            else:
                self.lbl_record.config(text="記録しませんでした", fg=th.INK_SUB)
            self.update_view()
            return
        if not rec.is_alive():
            self.app.recorder = None
            self.btn_record.set_text("⏺ 記録開始")
            self.update_view()
            return
        self.lbl_record.config(
            text="記録中… %d個（Escかホットキー/ボタンで終了）" % n, fg=th.INK)
        self.after(100, self._poll_record)

    def test_once(self):
        self.save()
        p = self.app.active_profile()
        ok, why = macro.send_seq({
            "send_mode": p.get("send_mode") or macro.DEFAULT_SEND_MODE,
            "steps": p.get("steps") or [], "hold_ms": p.get("hold_ms", 20),
            "target": p.get("target") or ""}, cycle=None)
        if why:
            self.lbl_sub.config(text="⚠ " + why)
        else:
            self.lbl_sub.config(
                text=("✅ %s を送りました" % self.app.macro_what()) if ok
                     else "⚠ 送れませんでした")

    def _wheel(self, e):
        try:
            self.canvas.yview_scroll(int(-e.delta / 120), "units")
        except tk.TclError:
            pass

    # ---------------- 表示更新 ----------------
    def toggle_hold(self):
        self.save()
        self.app.toggle_hold()
        self.update_view()

    def toggle(self, mode="hold"):
        self.save()
        self.app.toggle_macro(mode)
        self.update_view()

    def update_view(self):
        if not self.winfo_exists():
            return
        app = self.app
        running = app.macro_running()
        hold = running and app.macro_mode() == "hold"
        always = running and not hold
        self.btn.set_text("■ とめる" if hold else "▶ かまえる")
        self.btn_always.set_text("■ とめる" if always else "▶ ずっと実行")
        pressing = app.holder_running()
        self.btn_press.set_text("■ 離す" if pressing else "⬇ 長押し")

        for i, row in enumerate(self.step_rows):
            name = self.step_name(i)
            if self._capturing != "key%d" % i:
                if name == "key":
                    row["btn"].set_text("キー: %s" % macro.vk_name(row["vk"]))
                else:
                    row["btn"].set_text("（キーのときだけ）")
            if getattr(self, "_pos_target", None) != i or getattr(
                    self, "_pos_rec", None) is None:
                if name == "key":
                    row["btn_pos"].set_text("（マウスのときだけ）")
                else:
                    pos = row.get("pos")
                    row["btn_pos"].set_text("📍 (%d, %d)" % tuple(pos) if pos
                                            else "📍 場所を登録")

        for which, (btn, lbl) in self.lbl_hk.items():
            if self._capturing == "hotkey:" + which:
                continue
            text, name = app.hotkey_status(which)
            btn.set_text(name)
            lbl.config(text=text if text.startswith("⚠") else "")

        self.chk_rcancel.config(
            text="%sクリックでとめる" % ("左" if app.cancel_button() == "left" else "右"))

        p = app.active_profile()
        target = p.get("target") or ""
        if not target:
            self.lbl_found.config(text="  （空 = どこでも動きます）", fg=th.PINK_DK)
        elif wa.matches(target):
            self.lbl_found.config(text="  ✅ いま最前面です", fg=th.MINT)
        elif wa.find_window_cached(target):
            self.lbl_found.config(text="  ⏸ 起動中（前に出れば動きます）", fg=th.INK_SUB)
        else:
            self.lbl_found.config(text="  ⚠ 見つかりません", fg=th.PINK_DK)

        what = app.macro_what()
        if pressing:
            h = app.holder
            if h is not None and h.waiting:
                self.lbl_state.config(text="待機中（%s が前に出るまで）" % (target or "対象"),
                                      fg=th.INK_SUB)
            else:
                self.lbl_state.config(text="長押し中！", fg=th.MINT)
            self.lbl_sub.config(text="%s を押したままにしています。もう一度押すと離します"
                                     % app.macro_what(first=True))
            return
        if not running:
            just = app.cancelled_at and time.time() - app.cancelled_at < 6
            self.lbl_state.config(text="右クリックでとめました" if just else "とまっています",
                                  fg=th.PINK_DK if just else th.INK_SUB)
            self.lbl_sub.config(text="%s を %dミリ秒ごとに送ります"
                                     % (what, p.get("interval_ms", 100)))
            return
        r = app.macro
        if hold and r is not None and not r.holding:
            self.lbl_state.config(text="かまえ中（左クリックを押しっぱなしで実行）",
                                  fg=th.INK_SUB)
        elif r is not None and r.waiting:
            why = ("が見つかるまで" if p.get("send_mode", "input") != "input"
                   else "が前に出るまで")
            self.lbl_state.config(text="待機中（%s %s）" % (target, why), fg=th.INK_SUB)
        else:
            self.lbl_state.config(text="実行中！", fg=th.MINT)
        limit = int(p.get("limit") or 0)
        n = r.count if r is not None else 0
        self.lbl_sub.config(text="%s を %d回 送りました%s"
                            % (what, n, ("／ %d回で止まります" % limit) if limit else ""))


# ======================================================================
class SettingsDialog(tk.Toplevel):
    def __init__(self, app: App):
        super().__init__(app)
        self.app = app
        self.title("設定")
        self.configure(bg=th.BG)
        self.transient(app)
        F = app.F

        card = th.Card(self, bg=th.BG)
        card.pack(fill="both", expand=True, padx=10, pady=10)
        b = card.body
        tk.Label(b, text="見た目", bg=th.CARD, fg=th.INK, font=F["cute_b"]).pack(
            anchor="w")
        self.v_theme = tk.StringVar(value=app.cfg.get("theme", "cute"))
        for key in ("cute", "modern", "cool"):
            name = th.PALETTES[key]["NAME"]
            tk.Radiobutton(b, text=name, variable=self.v_theme, value=key,
                           bg=th.CARD, fg=th.INK, activebackground=th.CARD,
                           activeforeground=th.INK, selectcolor=th.FIELD,
                           font=F["cute"], bd=0, highlightthickness=0,
                           anchor="w").pack(anchor="w")
        tk.Label(b, text="変えると再起動します（設定・マクロはそのまま残ります）",
                 bg=th.CARD, fg=th.INK_SUB, font=F["small"]).pack(anchor="w",
                                                                  pady=(4, 10))

        self.v_top = tk.BooleanVar(value=bool(app.cfg.get("always_on_top")))
        tk.Checkbutton(b, text="常に最前面に表示", variable=self.v_top, bg=th.CARD,
                       fg=th.INK, activebackground=th.CARD, activeforeground=th.INK,
                       selectcolor=th.FIELD, font=F["cute"], bd=0,
                       highlightthickness=0, anchor="w").pack(anchor="w")

        btn = tk.Frame(b, bg=th.CARD)
        btn.pack(fill="x", pady=(14, 0))
        th.RoundButton(btn, "保存", self.apply, kind="primary", bg=th.CARD,
                       font=F["cute_b"], padx=20).pack(side="right")
        th.RoundButton(btn, "とじる", self.destroy, kind="soft", bg=th.CARD,
                       font=F["cute"]).pack(side="right", padx=8)

    def apply(self):
        app = self.app
        app.cfg["always_on_top"] = bool(self.v_top.get())
        app.attributes("-topmost", app.cfg["always_on_top"])
        theme_changed = self.v_theme.get() != app.cfg.get("theme", "cute")
        app.cfg["theme"] = self.v_theme.get()
        app.save_cfg()
        self.destroy()
        if theme_changed:
            app.restart()


# ======================================================================
class UpdateDialog(tk.Toplevel):
    def __init__(self, app: App):
        super().__init__(app)
        self.app = app
        self.info = None
        self.asset = None
        self.busy = False
        self.title("更新のかくにん")
        self.configure(bg=th.BG)
        self.geometry("540x420")
        self.minsize(500, 420)
        self.transient(app)
        self.attributes("-topmost", bool(app.cfg.get("always_on_top")))
        F = app.F

        card = th.Card(self, bg=th.BG)
        card.pack(fill="both", expand=True, padx=10, pady=10)
        b = card.body
        self.lbl_head = tk.Label(b, text="いま v%s です" % APP_VERSION, bg=th.CARD,
                                 fg=th.INK, font=F["cute_b"], anchor="w")
        self.lbl_head.pack(fill="x")
        self.lbl_state = tk.Label(b, text="たしかめています…", bg=th.CARD,
                                  fg=th.INK_SUB, font=F["small"], anchor="w",
                                  justify="left", wraplength=480)
        self.lbl_state.pack(fill="x", pady=(2, 8))

        btm = tk.Frame(b, bg=th.CARD)
        btm.pack(side="bottom", fill="x", pady=(10, 0))
        self.btn_go = th.RoundButton(btm, "いますぐ更新", self.do_update,
                                     kind="primary", bg=th.CARD, font=F["cute_b"],
                                     padx=22)
        th.RoundButton(btm, "とじる", self.destroy, kind="soft", bg=th.CARD,
                       font=F["cute"]).pack(side="right", padx=8)
        th.RoundButton(btm, "ページを開く", self.open_page, kind="ghost", bg=th.CARD,
                       font=F["small"]).pack(side="left")
        self.bar = th.RoundProgress(b, bg=th.CARD, color=th.LAV, height=6)

        box = tk.Frame(b, bg=th.FIELD)
        box.pack(fill="both", expand=True)
        self.txt = tk.Text(box, bg=th.FIELD, fg=th.INK, font=F["ui"], relief="flat",
                           bd=0, wrap="word", padx=12, pady=10, highlightthickness=0,
                           width=1, height=12)
        vs = ttk.Scrollbar(box, orient="vertical", command=self.txt.yview,
                           style="Cute.Vertical.TScrollbar")
        self.txt.configure(yscrollcommand=vs.set)
        vs.pack(side="right", fill="y")
        self.txt.pack(side="left", fill="both", expand=True)
        self.txt.configure(state="disabled")

        self._got_info = None
        self._prog = None
        self._done = None
        threading.Thread(target=self._check, daemon=True).start()
        self.after(120, self._poll)

    def _check(self):
        self._got_info = updater.check()

    def _poll(self):
        if not self.winfo_exists():
            return
        if self._got_info is not None:
            info, self._got_info = self._got_info, None
            self._show(info)
        if self._prog is not None:
            got, total = self._prog
            self._prog = None
            if total:
                self.bar.set(got / total)
        if self._done is not None:
            ok, why = self._done
            self._done = None
            if ok:
                self.app.on_close()
                return
            self._failed(why)
        self.after(120, self._poll)

    def _set_text(self, s):
        self.txt.configure(state="normal")
        self.txt.delete("1.0", "end")
        self.txt.insert("1.0", s)
        self.txt.configure(state="disabled")

    def _show(self, info):
        if not self.winfo_exists():
            return
        if not info.get("ok"):
            self.lbl_state.config(text="⚠ " + info.get("why", "失敗しました"), fg=th.PINK_DK)
            self._set_text("インターネットにつながっているか確かめてください。\n"
                          "「ページを開く」から手で取りにいくこともできます。")
            return
        self.info = info
        tag = info["tag"]
        body = (info.get("body") or "").lstrip("﻿").strip()
        self._set_text(body or "（更新内容が書かれていません）")
        if not updater.is_newer(tag, APP_VERSION):
            self.lbl_state.config(text="いちばん新しい版です（最新 %s）" % tag, fg=th.MINT)
            return

        kind = updater.install_kind()
        self.asset = updater.pick_asset(info, kind)
        self.lbl_head.config(text="v%s  →  %s があります" % (APP_VERSION, tag))
        if kind == "source":
            self.lbl_state.config(
                text="ソースから動いているので、ここからは更新できません。git pull してください",
                fg=th.PINK_DK)
            return
        if not self.asset:
            self.lbl_state.config(text="⚠ 入れ替えられるファイルが見つかりません", fg=th.PINK_DK)
            return
        how = {"installer": "インストーラで入れ替えます", "onedir": "フォルダを入れ替えます",
              "onefile": "exe を入れ替えます"}.get(kind, "入れ替えます")
        self.lbl_state.config(
            text="%s（%.1f MB）で%s。設定とマクロはそのまま残ります"
                 % (self.asset["name"], self.asset["size"] / 1024 / 1024, how),
            fg=th.INK_SUB)
        self.btn_go.pack(side="right")

    def open_page(self):
        webbrowser.open((self.info or {}).get("url") or updater.RELEASES_PAGE)

    def do_update(self):
        if self.busy or not self.asset:
            return
        self.busy = True
        self.btn_go.set_text("更新中…")
        self.bar.pack(side="bottom", fill="x", pady=(8, 0))
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        try:
            path = updater.download(
                self.asset, lambda got, total: setattr(self, "_prog", (got, total)))
            ok, why = updater.apply(path)
        except Exception as e:
            ok, why = False, "%s: %s" % (e.__class__.__name__, e)
        self._done = (ok, why)

    def _failed(self, why):
        self.busy = False
        self.btn_go.set_text("いますぐ更新")
        self.bar.pack_forget()
        self.lbl_state.config(text="⚠ 更新できませんでした: %s" % why, fg=th.PINK_DK)


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
