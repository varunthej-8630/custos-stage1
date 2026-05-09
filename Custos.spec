# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['run_server.py'],
    pathex=[],
    binaries=[],
    datas=[('C:\\Users\\dhany\\OneDrive\\Desktop\\VarunThej\\custos-stage1\\custos-stage1\\venv\\lib\\site-packages\\torch', 'torch'), ('C:\\Users\\dhany\\OneDrive\\Desktop\\VarunThej\\custos-stage1\\custos-stage1\\venv\\lib\\site-packages\\ultralytics', 'ultralytics'), ('C:\\Users\\dhany\\OneDrive\\Desktop\\VarunThej\\custos-stage1\\custos-stage1\\venv\\lib\\site-packages\\authlib', 'authlib'), ('C:\\Users\\dhany\\OneDrive\\Desktop\\VarunThej\\custos-stage1\\custos-stage1\\venv\\lib\\site-packages\\cryptography', 'cryptography'), ('frontend', 'frontend'), ('config', 'config'), ('.env', '.'), ('data/weights', 'data/weights')],
    hiddenimports=['engine.detector', 'engine.tracker', 'engine.zone_monitor', 'engine.risk_engine', 'web.alert_manager', 'updater', 'authlib.integrations.flask_client', 'flask_socketio', 'engine_io.async_drivers.threading'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['torch', 'ultralytics', 'authlib', 'cryptography'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Custos',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Custos',
)
