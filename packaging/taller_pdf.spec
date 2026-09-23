# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for Taller PDF (Windows .exe).

Build on a WINDOWS machine (PyInstaller produces binaries for the OS it runs on):

    cd backend
    pyinstaller ..\packaging\taller_pdf.spec --noconfirm

Output: dist\TallerPDF\TallerPDF.exe  (one-folder build — faster start, easy to zip).

Prerequisites the .exe expects on the target PC (NOT bundled — they are large native
suites): LibreOffice (soffice) and Ghostscript (gswin64c). See README_WINDOWS.md.
"""
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

# Run from the backend/ dir; the built SPA lives at ../frontend/dist
BACKEND = Path.cwd()
FRONTEND_DIST = (BACKEND.parent / "frontend" / "dist").resolve()

datas = []
binaries = []
hiddenimports = [
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
    "motor",
    "pymongo",
]

# Ship the built SPA inside the bundle as "frontend_dist" (desktop.py points FRONTEND_DIST here).
if FRONTEND_DIST.is_dir():
    datas.append((str(FRONTEND_DIST), "frontend_dist"))

# Heavy packages with data files / dynamic imports — pull everything so the frozen app finds them.
for pkg in ("pdf2docx", "fitz", "pymupdf", "cv2", "PIL", "pypdf", "fontTools", "docx"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:  # noqa: BLE001 — a package that isn't present is simply skipped
        pass

hiddenimports += collect_submodules("fastapi") + collect_submodules("starlette")

block_cipher = None

a = Analysis(
    ["desktop.py"],
    pathex=[str(BACKEND)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "pytest", "matplotlib"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TallerPDF",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,  # keep a console window: it shows the local URL and status
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="TallerPDF",
)
