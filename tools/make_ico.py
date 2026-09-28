# -*- coding: utf-8 -*-
"""theme.make_icon() の絵から Windows 用 .ico を作る（外部ライブラリ不要）。

Tk 8.6 の PhotoImage は PNG を書き出せるので、それを ICO に包むだけ。
    python tools/make_ico.py
→ assets/icon.ico （exeビルドで使う）
"""
import io
import os
import struct
import sys
import tkinter as tk

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)
sys.path.insert(0, PROJ)

import theme as th  # noqa: E402

# exe のアイコンは1つしか持てないので、見た目の設定に関係なく
# 「かわいい」の色（ピンク）で焼く。アプリの中のアイコンは
# 選んだ見た目に合わせて描き直される。
th.use("cute")

SIZES = (16, 32, 48, 64, 128, 256)


def png_bytes(root, size):
    img = th.make_icon(size)
    tmp = os.path.join(PROJ, "assets", "_tmp_%d.png" % size)
    img.write(tmp, format="png")
    with io.open(tmp, "rb") as f:
        data = f.read()
    os.remove(tmp)
    return data


def main():
    os.makedirs(os.path.join(PROJ, "assets"), exist_ok=True)
    root = tk.Tk()
    root.withdraw()
    th.init(root)
    pngs = [(s, png_bytes(root, s)) for s in SIZES]

    header = struct.pack("<HHH", 0, 1, len(pngs))
    entries = b""
    offset = 6 + 16 * len(pngs)
    for size, data in pngs:
        w = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", w, w, 0, 0, 1, 32, len(data), offset)
        offset += len(data)

    out = os.path.join(PROJ, "assets", "icon.ico")
    with io.open(out, "wb") as f:
        f.write(header)
        f.write(entries)
        for _s, data in pngs:
            f.write(data)
    print("wrote %s (%d bytes, %s)" % (out, os.path.getsize(out),
                                       ", ".join(str(s) for s, _ in pngs)))
    root.destroy()


if __name__ == "__main__":
    main()
