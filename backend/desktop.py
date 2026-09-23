"""
Desktop entry point for Taller PDF.

Runs the FastAPI app (which also serves the pre-built React SPA) on a local port and
opens the default browser. This is the module PyInstaller freezes into the .exe.

Everything is local: no external services, no Node process, no separate Mongo required
(the app is DB-free — the /api/tools/* endpoints never touch a database).

Prerequisites on the Windows machine (see packaging/README_WINDOWS.md):
  - LibreOffice        -> provides `soffice` for Word->PDF
  - Ghostscript        -> provides `gswin64c` for Compress PDF
Both are auto-located from PATH / standard install folders, or via the SOFFICE_BIN /
GS_BIN environment variables.
"""
import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path


def _base_dir() -> Path:
    # PyInstaller unpacks bundled data under sys._MEIPASS at runtime.
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent


def _pick_port(preferred: int = 8501) -> int:
    for port in (preferred, 8502, 8600, 8700, 0):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return s.getsockname()[1]
            except OSError:
                continue
    return preferred


def main() -> None:
    base = _base_dir()

    # The bundled SPA is shipped next to this script as "frontend_dist" (see the .spec).
    bundled_spa = base / "frontend_dist"
    if bundled_spa.is_dir():
        os.environ.setdefault("FRONTEND_DIST", str(bundled_spa))

    # DB-free defaults so a missing .env / offline Mongo never blocks boot.
    os.environ.setdefault("MONGO_URL", "mongodb://127.0.0.1:27017")
    os.environ.setdefault("DB_NAME", "taller_pdf")
    os.environ.setdefault("CORS_ORIGINS", "*")

    # server.py lives in the backend dir; make sure it is importable when frozen.
    backend_dir = base / "backend" if (base / "backend").is_dir() else base
    sys.path.insert(0, str(backend_dir))

    import uvicorn
    from server import app  # noqa: WPS433 — imported after sys.path is set

    port = _pick_port()
    url = f"http://127.0.0.1:{port}"

    def _open_browser() -> None:
        time.sleep(1.5)
        webbrowser.open(url)

    threading.Thread(target=_open_browser, daemon=True).start()
    print(f"\nTaller PDF en marcha -> {url}\n(Deja esta ventana abierta mientras uses la aplicación.)\n")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")


if __name__ == "__main__":
    main()
