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
- `/api/tools/convert-audio` — campo `files` (audio .mp3/.wav/.m4a/.flac/.aac/.ogg… o vídeo .mp4/.mov/.mkv/.avi/.webm…) + `target` (mp3|wav|flac|m4a) + opcionales `bitrate` (128|192|320, solo mp3/m4a), `normalize` (bool → loudnorm EBU R128), `start`/`end` (recorte, seg o mm:ss) → audio (1 archivo) o ZIP (2+). Vía ffmpeg (`-vn`, `-ss`/`-to` antes de `-i`). Requiere ffmpeg (FFMPEG_BIN auto-localizado).
- `/api/tools/convert-video` — campo `files` (≥1 vídeo .mp4/.mov/.mkv/.avi/.webm…) + `target` (mp4|mov|avi|mkv) + opcionales `scale` (original|2160|1440|1080|720|480|360, `-vf scale=-2:h`) y `quality` (ligera|recomendada|maxima → CRF 20/23/28, libx264+aac) → vídeo (1 archivo) o ZIP (2+). 3 tarjetas UI (Convertir, Cambiar resolución, Comprimir) sobre este endpoint. Requiere ffmpeg.
- `/api/tools/merge-audio` — campo `files` (≥2 audio/vídeo) + `target` (mp3|wav|flac|m4a) + opcionales `bitrate`, `normalize` → un único audio continuo (ffmpeg `concat` filter). Requiere ffmpeg.
- `/api/tools/convert-image` — campo `files` (≥1 .jpg/.jpeg/.png/.bmp/.webp/.tif/.tiff) + `target` (jpg|png) → imagen (1 archivo) o ZIP (2+). PNG sin pérdidas (optimize), JPEG quality=95 subsampling=0 aplanando alfa sobre blanco. Cubre las 8 conversiones (JPG/PNG/BMP/WEBP/TIFF → JPG o PNG).

## Frontend
- Página única (`/`, `src/pages/Home.tsx`) con **pestañas** (Tabs): "Documentos" (Word→PDF, PDF→Word, Unir, Dividir, Comprimir) e "Imagen" (Convertir imágenes, Imágenes a PDF). Al elegir una tarjeta se abre `ToolPanel` dentro de la pestaña.
- Idioma ES/CA con conmutador en la cabecera, persistido en `localStorage` (`pdf-workshop-lang`), diccionarios en `src/lib/i18n.ts`.
- Subida binaria con `apiUploadFile` / `downloadBlob` en `src/lib/api.ts`.

## Sin autenticación ni cuentas.
- Recorte con **vista de onda**: `src/components/WaveformTrimmer.tsx` decodifica el audio con Web Audio API (local) y deja arrastrar inicio/fin; para vídeo o si falla la decodificación cae a inputs numéricos. Herramientas Audio: Convertir audio, Extraer audio de vídeo, Unir pistas.

## Empaquetado como .exe de Windows (packaging/)
- `backend/desktop.py`: entrypoint que arranca uvicorn en 127.0.0.1 y abre el navegador; FastAPI sirve el SPA pre-construido (bloque estático al final de `server.py`, activo solo si existe `frontend/dist` o `FRONTEND_DIST`).
- `packaging/taller_pdf.spec` (PyInstaller), `packaging/build_windows.bat`, `packaging/README_WINDOWS.md`.
- DB-free: `lib/db.py` usa defaults, la app arranca sin Mongo. Binarios `soffice`/`gswin64c` se auto-localizan (PATH o rutas estándar de Windows) o vía `SOFFICE_BIN`/`GS_BIN`.
- El .exe se compila EN Windows (PyInstaller es específico de plataforma). Requiere LibreOffice y Ghostscript instalados en el equipo de destino.
