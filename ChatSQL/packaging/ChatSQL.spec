# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules


root = Path.cwd()
backend = root / "backend"
frontend_dist = root / "frontend" / "dist"
seed = backend / "app" / "seed"

datas = []
if frontend_dist.exists():
    datas.append((str(frontend_dist), "frontend/dist"))
if seed.exists():
    datas.append((str(seed), "app/seed"))

a = Analysis(
    [str(backend / "app" / "desktop_main.py")],
    pathex=[str(backend)],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "duckdb",
        "numpy",
        "openpyxl",
        "pandas",
        "pymysql",
        "uvicorn.logging",
        "uvicorn.loops.auto",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan.on",
    ] + collect_submodules("sqlglot"),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ChatSQL",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="ChatSQL",
)
