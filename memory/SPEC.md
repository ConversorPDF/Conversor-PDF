# Taller PDF — spec

App web interna tipo iLovePDF. Todo el procesamiento es local (LibreOffice headless, pdf2docx, pypdf, Pillow). Sin servicios externos. Sin base de datos: los endpoints son stateless y los temporales se borran tras la respuesta (BackgroundTask).

## Endpoints (todos POST multipart, bajo /api)
- `/api/tools/word-to-pdf` — campo `files` (≥1 .docx/.doc/.odt/.rtf) → PDF (1 archivo) o ZIP (2+)
- `/api/tools/pdf-to-word` — campo `file` (.pdf) → DOCX
- `/api/tools/merge-pdf` — campo `files` (≥2 .pdf) → PDF unido
- `/api/tools/split-pdf` — campo `file` (.pdf) + `ranges` ("1-3,5"; vacío = una página por archivo) → PDF (1 rango) o ZIP (varios)
- `/api/tools/images-to-pdf` — campo `files` (.jpg/.jpeg/.png/.webp) → PDF
- `/api/tools/compress-pdf` — campo `file` (.pdf) + `level` (ligera=/printer, recomendada=/ebook, maxima=/screen) → PDF; cabeceras `X-Original-Size`, `X-Compressed-Size`, `X-Reduction-Percent` (Ghostscript). Si el resultado no encoge, devuelve el original (reducción 0%).

Errores: 400 formato/rango inválido o pocos archivos, 413 >100 MB, 500 fallo de conversión. Cuerpo `{"detail": "..."}`.

## Frontend
- Una sola página (`/`, `src/pages/Home.tsx`) con 5 tarjetas de herramienta; al elegir una se abre `ToolPanel` (drag & drop, lista de archivos, rangos, barra de progreso XHR, descarga automática vía blob).
- Idioma ES/CA con conmutador en la cabecera, persistido en `localStorage` (`pdf-workshop-lang`), diccionarios en `src/lib/i18n.ts`.
- Subida binaria con `apiUploadFile` / `downloadBlob` en `src/lib/api.ts`.

## Sin autenticación ni cuentas.

## Empaquetado como .exe de Windows (packaging/)
- `backend/desktop.py`: entrypoint que arranca uvicorn en 127.0.0.1 y abre el navegador; FastAPI sirve el SPA pre-construido (bloque estático al final de `server.py`, activo solo si existe `frontend/dist` o `FRONTEND_DIST`).
- `packaging/taller_pdf.spec` (PyInstaller), `packaging/build_windows.bat`, `packaging/README_WINDOWS.md`.
- DB-free: `lib/db.py` usa defaults, la app arranca sin Mongo. Binarios `soffice`/`gswin64c` se auto-localizan (PATH o rutas estándar de Windows) o vía `SOFFICE_BIN`/`GS_BIN`.
- El .exe se compila EN Windows (PyInstaller es específico de plataforma). Requiere LibreOffice y Ghostscript instalados en el equipo de destino.
