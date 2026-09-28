# -*- coding: utf-8 -*-
"""GitHub のリリースを見て、新しい版があれば入れ替える。

  check()    … 最新リリースの情報を取ってくる（バージョン・更新内容・ファイル）
  download() … zip か exe を一時フォルダに落とす
  apply()    … 落としたものを入れ替えて、アプリを起動し直す

実行中の exe は自分自身を上書きできないので、
「このプロセスの終了を待つ → 差し替える → 起動し直す」バッチを書いて起動し、
こちらは終了する、という段取りにしている。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

REPO = "Simohayhe/pochi-macro"
API = "https://api.github.com/repos/%s/releases/latest" % REPO
RELEASES_PAGE = "https://github.com/%s/releases" % REPO
UA = "PochiMacro-Updater"


def parse_version(text):
    """'v1.11.1' -> (1, 11, 1)。数字が拾えなければ (0,)。"""
    nums = re.findall(r"\d+", text or "")
    return tuple(int(x) for x in nums[:4]) or (0,)


def is_newer(latest, current):
    a, b = parse_version(latest), parse_version(current)
    n = max(len(a), len(b))
    a += (0,) * (n - len(a))
    b += (0,) * (n - len(b))
    return a > b


# ---------------------------------------------------------------- 今の形態
def install_kind():
    """'installer' / 'onedir' / 'onefile' / 'source' のどれで動いているか。

    installer = インストーラで入れたもの（隣に unins000.exe がある）。
    この場合は setup.exe を当て直すのが正しい。フォルダを上書きするだけだと、
    「設定 → アプリ」に出るバージョンが古いままになってしまう。
    """
    if not getattr(sys, "frozen", False):
        return "source"
    meipass = getattr(sys, "_MEIPASS", "")
    exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    # onedir は展開先＝exeの隣（_internal）。onefile は %TEMP% に展開される。
    if meipass and os.path.normcase(os.path.dirname(meipass.rstrip("\\/"))) \
            != os.path.normcase(exe_dir):
        if not os.path.isdir(os.path.join(exe_dir, "_internal")):
            return "onefile"
    if os.path.exists(os.path.join(exe_dir, "unins000.exe")):
        return "installer"
    return "onedir"


def install_dir():
    return os.path.dirname(os.path.abspath(sys.executable))


# ---------------------------------------------------------------- 確認
def check(timeout=10):
    """最新リリースを見に行く。取れなければ {'ok': False, 'why': ...}。"""
    req = urllib.request.Request(API, headers={"User-Agent": UA,
                                               "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.load(r)
    except Exception as e:
        return {"ok": False, "why": "たしかめられませんでした（%s）" % e.__class__.__name__}

    assets = []
    for a in data.get("assets") or []:
        assets.append({"name": a.get("name") or "",
                       "url": a.get("browser_download_url") or "",
                       "size": a.get("size") or 0})
    return {
        "ok": True,
        "tag": data.get("tag_name") or "",
        "title": data.get("name") or "",
        "body": data.get("body") or "",
        "url": data.get("html_url") or RELEASES_PAGE,
        "assets": assets,
    }


def pick_asset(info, kind):
    """今の形態に合うファイルを選ぶ。"""
    zip_a = exe_a = setup_a = None
    for a in info.get("assets") or []:
        low = a["name"].lower()
        if low.endswith(".zip"):
            zip_a = zip_a or a
        elif low.endswith("setup.exe"):
            setup_a = setup_a or a
        elif low.endswith(".exe"):
            exe_a = exe_a or a
    if kind == "installer":
        return setup_a or zip_a or exe_a
    if kind == "onefile":
        return exe_a or zip_a
    return zip_a or exe_a


# ---------------------------------------------------------------- 取得
def download(asset, on_progress=None, timeout=60):
    """一時フォルダに落として、そのパスを返す。"""
    tmp = os.path.join(tempfile.gettempdir(), "pochimacro_update")
    os.makedirs(tmp, exist_ok=True)
    dest = os.path.join(tmp, asset["name"])
    req = urllib.request.Request(asset["url"], headers={"User-Agent": UA})
    total = int(asset.get("size") or 0)
    got = 0
    with urllib.request.urlopen(req, timeout=timeout) as r, open(dest, "wb") as f:
        while True:
            chunk = r.read(64 * 1024)
            if not chunk:
                break
            f.write(chunk)
            got += len(chunk)
            if on_progress:
                on_progress(got, total)
    if total and os.path.getsize(dest) != total:
        raise IOError("ダウンロードが途中で切れました")
    return dest


# ---------------------------------------------------------------- 入れ替え
BAT_TEMPLATE = """@echo off
chcp 65001 >nul
rem PochiMacro の更新用。終わったら自分を消す。
:wait
tasklist /FI "PID eq {pid}" 2>nul | find "{pid}" >nul
if not errorlevel 1 (
  ping -n 2 127.0.0.1 >nul
  goto wait
)
{action}
start "" "{exe}"
del "%~f0"
"""


def apply(downloaded, on_log=None):
    """落としたものを入れ替えるバッチを起動して、True を返したら自分を終了する。"""
    kind = install_kind()
    if kind == "source":
        return False, "ソースから動いているので、git pull で更新してください"

    exe = os.path.abspath(sys.executable)
    target_dir = install_dir()
    pid = os.getpid()
    tmp = os.path.dirname(downloaded)

    if downloaded.lower().endswith("setup.exe"):
        # インストーラに任せる。アプリを閉じるのも登録の更新も向こうがやる。
        action = '"%s" /VERYSILENT /NORESTART /SUPPRESSMSGBOXES' % downloaded
    elif downloaded.lower().endswith(".zip"):
        # zip の中は PochiMacro/ になっている
        unpack = os.path.join(tmp, "unpacked")
        if os.path.isdir(unpack):
            import shutil
            shutil.rmtree(unpack, ignore_errors=True)
        with zipfile.ZipFile(downloaded) as z:
            z.extractall(unpack)
        inner = os.path.join(unpack, "PochiMacro")
        src = inner if os.path.isdir(inner) else unpack
        # robocopy は 0〜7 が成功扱いなので、エラー判定はしない
        action = 'robocopy "%s" "%s" /E /IS /IT /R:2 /W:1 >nul' % (src, target_dir)
    else:
        action = 'move /y "%s" "%s" >nul' % (downloaded, exe)

    bat = os.path.join(tmp, "pochimacro_update.bat")
    with open(bat, "w", encoding="utf-8") as f:
        f.write(BAT_TEMPLATE.format(pid=pid, action=action, exe=exe))
    if on_log:
        on_log("入れ替えて起動し直します…")
    subprocess.Popen(["cmd", "/c", bat],
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return True, ""
