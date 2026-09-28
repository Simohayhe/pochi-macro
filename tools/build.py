# -*- coding: utf-8 -*-
"""exe をビルドする。

    python tools/build.py            # onefile / onedir(zip) / setup.exe の全部
    python tools/build.py onefile    # onefile だけ
    python tools/build.py onedir     # onedir(zip) だけ
    python tools/build.py setup      # インストーラだけ（onedir を先に作る）

Windows Defender の誤検知（Trojan:Win32/Wacatac.*!ml）対策として、
このスクリプトは次を必ず行う:

  * UPX を使わない        … 圧縮された exe は問答無用で疑われる
  * バージョン情報を埋める … 会社名・製品名・著作権が空の exe は疑われる
  * onedir 版も一緒に作る  … onefile は %TEMP% に自己展開するので
                             機械学習判定に引っかかりやすい。
                             フォルダ版はその挙動が無く、かなり通りやすい

最後に Defender でスキャンして結果を出す。
"""
import os
import shutil
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)
sys.path.insert(0, PROJ)

NAME = "PochiMacro"
VERSION_FILE = os.path.join(PROJ, "build_version_info.txt")


def app_version():
    """pochi_macro.py の APP_VERSION を読む（GUIを起動せずに）。"""
    path = os.path.join(PROJ, "pochi_macro.py")
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.startswith("APP_VERSION"):
                return line.split("=", 1)[1].strip().strip('"\'')
    return "0.0.0"


def write_version_info(ver):
    """exe のプロパティに出る情報。空だと Defender の心証が悪い。"""
    parts = [int(x) for x in ver.split(".")]
    while len(parts) < 4:
        parts.append(0)
    quad = tuple(parts[:4])
    text = """VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=%(q)s, prodvers=%(q)s,
    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('041104b0', [
      StringStruct('CompanyName', 'Simohaya'),
      StringStruct('FileDescription', 'PochiMacro'),
      StringStruct('FileVersion', '%(v)s'),
      StringStruct('InternalName', '%(n)s'),
      StringStruct('LegalCopyright',
                   'Copyright (c) 2026 Simohaya. MIT License.'),
      StringStruct('OriginalFilename', '%(n)s.exe'),
      StringStruct('ProductName', 'PochiMacro'),
      StringStruct('ProductVersion', '%(v)s'),
      StringStruct('Comments',
                   'Open source. https://github.com/Simohayhe/pochi-macro')])]),
    VarFileInfo([VarStruct('Translation', [1041, 1200])])
  ]
)
""" % {"q": quad, "v": ver, "n": NAME}
    with open(VERSION_FILE, "w", encoding="utf-8") as f:
        f.write(text)
    return VERSION_FILE


SPEC_NOTE = """# -*- mode: python ; coding: utf-8 -*-
#
# このファイルは tools/build.py が自動生成する。直接編集しても次のビルドで消える。
#
# upx は必ず False のままにすること。
# True にすると Windows Defender に Trojan:Win32/Wacatac.C!ml として
# 誤検知されうる。version-file（会社名・製品名・著作権）を入れておくのも
# 誤検知対策（ark-breeding-timer で2026-08-03に実際に踏んだ事例に倣う）。
#
"""


def keep_spec_note(spec_name):
    """自動生成された spec の先頭に、UPX 禁止の理由を書き戻す。"""
    path = os.path.join(PROJ, spec_name)
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        body = f.read()
    body = body.split("\n", 1)[1] if body.startswith("# -*- mode: python") else body
    with open(path, "w", encoding="utf-8") as f:
        f.write(SPEC_NOTE + body.lstrip("\n"))


def run(args):
    print("$ " + " ".join(args))
    r = subprocess.run(args, cwd=PROJ)
    if r.returncode != 0:
        sys.exit("ビルドに失敗しました (exit %d)" % r.returncode)


def common_args(ver):
    return [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--noconsole", "--noupx",
        "--icon", os.path.join("assets", "icon.ico"),
        "--version-file", write_version_info(ver),
        "--hidden-import", "theme", "--hidden-import", "updater",
        "--hidden-import", "macro_engine", "--hidden-import", "winapi",
        "pochi_macro.py",
    ]


def build_onefile(ver):
    args = common_args(ver)
    args[args.index("pochi_macro.py"):] = [
        "--onefile", "--name", NAME, "pochi_macro.py"]
    run(args)
    keep_spec_note(NAME + ".spec")
    return os.path.join(PROJ, "dist", NAME + ".exe")


def build_onedir(ver):
    dirname = NAME + "-dir"
    args = common_args(ver)
    args[args.index("pochi_macro.py"):] = [
        "--onedir", "--name", dirname, "pochi_macro.py"]
    run(args)
    keep_spec_note(dirname + ".spec")
    src = os.path.join(PROJ, "dist", dirname)
    # PyInstaller は出力名で exe を作るので "-dir" が付いてしまう。
    # zip も setup.exe もこのフォルダを使うので、ここで正しい名前に直す。
    made = os.path.join(src, dirname + ".exe")
    want = os.path.join(src, NAME + ".exe")
    if os.path.exists(made):
        if os.path.exists(want):
            os.remove(want)
        os.rename(made, want)
    # zip の中は「PochiMacro/」にしたいので入れ直す
    zip_path = os.path.join(PROJ, "dist", "%s-%s-win64.zip" % (NAME, ver))
    if os.path.exists(zip_path):
        os.remove(zip_path)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _dirs, files in os.walk(src):
            for fn in files:
                full = os.path.join(root, fn)
                rel = os.path.relpath(full, src)
                if rel.lower() == dirname.lower() + ".exe":
                    rel = NAME + ".exe"
                z.write(full, os.path.join(NAME, rel))
    return zip_path


ISCC_CANDIDATES = (
    r"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe",
    r"%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe",
    r"%ProgramFiles%\Inno Setup 6\ISCC.exe",
)


def find_iscc():
    for p in ISCC_CANDIDATES:
        p = os.path.expandvars(p)
        if os.path.exists(p):
            return p
    return shutil.which("ISCC") or shutil.which("iscc")


def build_setup(ver):
    """Inno Setup で setup.exe を作る。onedir の中身をそのまま詰める。"""
    iscc = find_iscc()
    if not iscc:
        print("  ! Inno Setup が見つからないので setup.exe は作りません")
        print("    winget install JRSoftware.InnoSetup で入ります")
        return None
    src = os.path.join(PROJ, "dist", NAME + "-dir")
    if not os.path.isdir(src):
        print("  ! %s が無いので、先に onedir を作ってください" % src)
        return None
    iss = os.path.join(PROJ, "installer", "PochiMacro.iss")
    run([iscc, "/DMyVersion=" + ver, iss])
    return os.path.join(PROJ, "dist", "%s-%s-setup.exe" % (NAME, ver))


def defender_scan(path):
    mp = os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"),
                      "Windows Defender", "MpCmdRun.exe")
    if not os.path.exists(path):
        return "（消えています。Defender に隔離された可能性）"
    if not os.path.exists(mp):
        return "（MpCmdRun.exe が見つからないのでスキャン省略）"
    r = subprocess.run([mp, "-Scan", "-ScanType", "3", "-File", path],
                       capture_output=True, text=True, errors="replace")
    out = (r.stdout or "") + (r.stderr or "")
    if "found no threats" in out or "見つかりませんでした" in out:
        return "OK（検出なし）"
    return "⚠ 何か出ました:\n" + out.strip()


def main():
    what = (sys.argv[1] if len(sys.argv) > 1 else "all").lower()
    ver = app_version()
    print("=== %s v%s をビルドします ===" % (NAME, ver))
    made = []
    if what in ("all", "onefile"):
        made.append(build_onefile(ver))
    if what in ("all", "onedir", "setup"):
        made.append(build_onedir(ver))
    if what in ("all", "setup"):
        setup = build_setup(ver)
        if setup:
            made.append(setup)
    stray = os.path.join(PROJ, "dist", NAME + "-dir")
    if os.path.isdir(stray):
        shutil.rmtree(stray, ignore_errors=True)

    print("\n=== できあがり ===")
    for p in made:
        size = os.path.getsize(p) / 1024 / 1024 if os.path.exists(p) else 0
        print("  %-52s %6.2f MB" % (os.path.basename(p), size))
        print("      Defender: %s" % defender_scan(p))


if __name__ == "__main__":
    main()
