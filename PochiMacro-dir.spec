# -*- mode: python ; coding: utf-8 -*-
#
# このファイルは tools/build.py が自動生成する。直接編集しても次のビルドで消える。
#
# upx は必ず False のままにすること。
# True にすると Windows Defender に Trojan:Win32/Wacatac.C!ml として
# 誤検知されうる。version-file（会社名・製品名・著作権）を入れておくのも
# 誤検知対策（ark-breeding-timer で2026-08-03に実際に踏んだ事例に倣う）。
#
a = Analysis(
    ['pochi_macro.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=['theme', 'updater', 'macro_engine', 'winapi'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='PochiMacro-dir',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version='C:\\Users\\master\\Desktop\\作業場\\pochi-macro\\build_version_info.txt',
    icon=['assets\\icon.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='PochiMacro-dir',
)
