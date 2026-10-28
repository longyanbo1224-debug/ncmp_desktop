# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [('app/ui/fonts', 'ui/fonts'), ('app/ui/styles/check.png', 'ui/styles'), ('resources/workflow_example.yml', 'resources'), ('resources/app.ico', 'resources')]
binaries = []
hiddenimports = ['keyring.backends', 'keyring.backends.Windows']
tmp_ret = collect_all('qtawesome')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('pyncm')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['app/main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PySide6.QtWebEngineWidgets', 'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineQuick', 'PySide6.QtQml', 'PySide6.QtQuick', 'PySide6.QtQuick3D', 'PySide6.QtQuickWidgets', 'PySide6.Qt3DCore', 'PySide6.Qt3DRender', 'PySide6.QtCharts', 'PySide6.QtDataVisualization', 'PySide6.QtMultimedia', 'PySide6.QtMultimediaWidgets', 'PySide6.QtPdf', 'PySide6.QtPdfWidgets', 'PySide6.QtSql', 'PySide6.QtTest', 'torch', 'tensorflow', 'pandas', 'scipy', 'matplotlib', 'IPython', 'jupyter', 'notebook'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ncmp desktop',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['resources/app.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='ncmp desktop',
)
