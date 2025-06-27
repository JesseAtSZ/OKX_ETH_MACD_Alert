# -*- mode: python ; coding: utf-8 -*-
block_cipher = None

added_files = [('alert.wav', '.')]  # 添加告警提示音文件

os.environ['MPLBACKEND'] = 'TkAgg'  # 强制 matplotlib 使用 TkAgg backend

a = Analysis(
    ['ETH Monitor'],
    pathex=[],
    binaries=[],
    datas=added_files,
    hiddenimports=[
        'talib',
        'tkinter',
        'threading',
        'time',
        'ccxt',
        'winsound',
        'traceback',
        'datetime',
        'sqlite3',
        'pandas',
        'logging',
        'mplfinance'
    ],
    hookspath=['.'],
    hooksconfig={},
    runtime_hooks=[],
    noarchive=False,
    optimize=2,  # 开启优化
)
pyz = PYZ(a.pure, a.zipped_data,
             cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='ETH 监控',
    debug=False,
    bootloader_ignore_signals=False,
    strip=True,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='eth.ico'
)
coll = COLLECT(exe,
               a.binaries,
               a.zipfiles,
               a.datas,
               strip=True,
               upx=True,
               upx_exclude=[],
               name='ETH Monitor')