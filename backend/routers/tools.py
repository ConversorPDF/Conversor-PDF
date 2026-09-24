"""Local PDF/Office tooling — all processing happens in-pod, no external services."""
import asyncio
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import List

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

import glob

router = APIRouter(prefix="/tools", tags=["tools"])

MAX_BYTES = 100 * 1024 * 1024  # 100 MB per file


def _soffice_bin() -> str:
    """Locate LibreOffice's soffice. Env override wins, then PATH, then common Windows paths."""
    if override := os.environ.get("SOFFICE_BIN"):
        return override
    for name in ("soffice", "soffice.exe"):
        if found := shutil.which(name):
            return found
    for path in (
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    ):
        if os.path.isfile(path):
            return path
    return "soffice"  # last resort — subprocess raises a clear error if truly missing


def _ffmpeg_bin() -> str:
    """Locate ffmpeg. Env override wins, then PATH, then common Windows paths."""
    if override := os.environ.get("FFMPEG_BIN"):
        return override
    for name in ("ffmpeg", "ffmpeg.exe"):
        if found := shutil.which(name):
            return found
    for path in (r"C:\Program Files\ffmpeg\bin\ffmpeg.exe", r"C:\ffmpeg\bin\ffmpeg.exe"):
        if os.path.isfile(path):
            return path
    return "ffmpeg"


def _gs_bin() -> str:
    """Locate Ghostscript. Env override wins, then PATH (gs/gswin64c/gswin32c), then Windows paths."""
    if override := os.environ.get("GS_BIN"):
        return override
    for name in ("gs", "gswin64c", "gswin32c"):
        if found := shutil.which(name):
            return found
    for pattern in (
        r"C:\Program Files\gs\gs*\bin\gswin64c.exe",
        r"C:\Program Files\gs\gs*\bin\gswin32c.exe",
    ):
        if hits := sorted(glob.glob(pattern)):
            return hits[-1]
    return "gs"


def _cleanup(path: str):
    shutil.rmtree(path, ignore_errors=True)


def _check_ext(upload: UploadFile, allowed: tuple[str, ...]):
    name = (upload.filename or "").lower()
    if not name.endswith(allowed):
        raise HTTPException(
            status_code=400,
            detail=f"Formato no soportado: {upload.filename or 'archivo'}. Se esperaba {', '.join(allowed)}",
        )


async def _save(upload: UploadFile, dest: Path) -> Path:
    size = 0
    with dest.open("wb") as fh:
        while chunk := await upload.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_BYTES:
                raise HTTPException(status_code=413, detail="El archivo supera el límite de 100 MB")
            fh.write(chunk)
    if size == 0:
        raise HTTPException(status_code=400, detail="El archivo está vacío")
    return dest


def _respond(path: Path, workdir: str, media_type: str, extra_headers: dict | None = None) -> FileResponse:
    headers = {"Content-Disposition": f'attachment; filename="{path.name}"'}
    if extra_headers:
        headers.update(extra_headers)
    return FileResponse(
        path,
        media_type=media_type,
        filename=path.name,
        headers=headers,
        background=BackgroundTask(_cleanup, workdir),  # temp files deleted after the response
    )


def _soffice(src: Path, outdir: Path) -> Path:
    subprocess.run(
        [_soffice_bin(), "--headless", "--norestore", "--convert-to", "pdf", "--outdir", str(outdir), str(src)],
        check=True,
        capture_output=True,
        timeout=300,
        env={**os.environ, "HOME": str(outdir)},
    )
    out = outdir / (src.stem + ".pdf")
    if not out.exists():
        raise HTTPException(status_code=500, detail="La conversión no produjo un PDF")
    return out


@router.post("/word-to-pdf")
async def word_to_pdf(files: List[UploadFile] = File(...)):
    if not files:
        raise HTTPException(status_code=400, detail="Selecciona al menos un archivo")
    for f in files:
        _check_ext(f, (".docx", ".doc", ".odt", ".rtf"))
    workdir = tempfile.mkdtemp(prefix="w2p_")
    try:
        pdfs: list[Path] = []
        for i, f in enumerate(files):
            sub = Path(workdir) / f"src_{i}"
            sub.mkdir()
            src = await _save(f, sub / Path(f.filename or f"documento_{i}.docx").name)
            out = await asyncio.to_thread(_soffice, src, sub)
            final = Path(workdir) / (Path(f.filename or f"documento_{i}").stem + ".pdf")
            shutil.move(str(out), str(final))
            pdfs.append(final)
        if len(pdfs) == 1:
            return _respond(pdfs[0], workdir, "application/pdf")
        zip_path = Path(workdir) / "documentos-pdf.zip"
        used: dict[str, int] = {}
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in pdfs:
                arc = p.name
                if arc in used:
                    used[arc] += 1
                    arc = f"{p.stem}_{used[p.name]}.pdf"
                else:
                    used[arc] = 0
                zf.write(p, arc)
    except HTTPException:
        _cleanup(workdir)
        raise
    except Exception as exc:  # noqa: BLE001
        _cleanup(workdir)
        raise HTTPException(status_code=500, detail=f"Error al convertir: {exc}") from exc
    return _respond(zip_path, workdir, "application/zip")


_GS_QUALITY = {"ligera": "/printer", "recomendada": "/ebook", "maxima": "/screen"}


@router.post("/compress-pdf")
async def compress_pdf(file: UploadFile = File(...), level: str = Form("recomendada")):
    _check_ext(file, (".pdf",))
    quality = _GS_QUALITY.get(level, "/ebook")
    workdir = tempfile.mkdtemp(prefix="comp_")
    try:
        src = await _save(file, Path(workdir) / "entrada.pdf")
        original = src.stat().st_size
        out = Path(workdir) / (Path(file.filename or "documento").stem + "_comprimido.pdf")

        def _gs():
            subprocess.run(
                [
                    _gs_bin(), "-sDEVICE=pdfwrite", "-dCompatibilityLevel=1.4",
                    f"-dPDFSETTINGS={quality}", "-dNOPAUSE", "-dQUIET", "-dBATCH",
                    "-dDetectDuplicateImages=true", f"-sOutputFile={out}", str(src),
                ],
                check=True, capture_output=True, timeout=300,
            )

        await asyncio.to_thread(_gs)
        if not out.exists() or out.stat().st_size == 0:
            raise HTTPException(status_code=500, detail="La compresión no produjo un PDF")
        compressed = out.stat().st_size
        # If Ghostscript enlarged the file (already-optimised PDF), return the original instead.
        if compressed >= original:
            shutil.copyfile(src, out)
            compressed = original
        reduction = 0 if original == 0 else round((1 - compressed / original) * 100)
    except HTTPException:
        _cleanup(workdir)
        raise
    except Exception as exc:  # noqa: BLE001
        _cleanup(workdir)
        raise HTTPException(status_code=500, detail=f"Error al comprimir: {exc}") from exc
    return _respond(
        out, workdir, "application/pdf",
        extra_headers={
            "X-Original-Size": str(original),
            "X-Compressed-Size": str(compressed),
            "X-Reduction-Percent": str(reduction),
        },
    )


def _pdf_to_docx(src: Path, out: Path):
    from pdf2docx import Converter

    cv = Converter(str(src))
    try:
        cv.convert(str(out))
    finally:
        cv.close()


@router.post("/pdf-to-word")
async def pdf_to_word(file: UploadFile = File(...)):
    _check_ext(file, (".pdf",))
    workdir = tempfile.mkdtemp(prefix="p2w_")
    try:
        src = await _save(file, Path(workdir) / "entrada.pdf")
        out = Path(workdir) / (Path(file.filename or "documento").stem + ".docx")
        await asyncio.to_thread(_pdf_to_docx, src, out)
        if not out.exists():
            raise HTTPException(status_code=500, detail="La conversión no produjo un DOCX")
    except HTTPException:
        _cleanup(workdir)
        raise
    except Exception as exc:  # noqa: BLE001
        _cleanup(workdir)
        raise HTTPException(status_code=500, detail=f"Error al convertir: {exc}") from exc
    return _respond(
        out, workdir, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )


@router.post("/merge-pdf")
async def merge_pdf(files: List[UploadFile] = File(...)):
    if len(files) < 2:
        raise HTTPException(status_code=400, detail="Selecciona al menos 2 archivos PDF")
    for f in files:
        _check_ext(f, (".pdf",))
    workdir = tempfile.mkdtemp(prefix="merge_")
    try:
        from pypdf import PdfWriter

        writer = PdfWriter()
        for i, f in enumerate(files):
            p = await _save(f, Path(workdir) / f"in_{i}.pdf")
            writer.append(str(p))
        out = Path(workdir) / "documento-unido.pdf"
        with out.open("wb") as fh:
            writer.write(fh)
        writer.close()
    except HTTPException:
        _cleanup(workdir)
        raise
    except Exception as exc:  # noqa: BLE001
        _cleanup(workdir)
        raise HTTPException(status_code=500, detail=f"Error al unir: {exc}") from exc
    return _respond(out, workdir, "application/pdf")


def _parse_ranges(spec: str, total: int) -> list[tuple[int, int]]:
    spec = (spec or "").strip()
    if not spec:
        return [(i, i) for i in range(1, total + 1)]
    out: list[tuple[int, int]] = []
    for part in re.split(r"[,\s]+", spec):
        if not part:
            continue
        m = re.fullmatch(r"(\d+)(?:-(\d+))?", part)
        if not m:
            raise HTTPException(status_code=400, detail=f"Rango no válido: {part}")
        start = int(m.group(1))
        end = int(m.group(2) or start)
        if start < 1 or end < start or end > total:
            raise HTTPException(
                status_code=400, detail=f"Rango fuera de los límites (1-{total}): {part}"
            )
        out.append((start, end))
    if not out:
        raise HTTPException(status_code=400, detail="Indica al menos un rango de páginas")
    return out


@router.post("/split-pdf")
async def split_pdf(file: UploadFile = File(...), ranges: str = Form("")):
    _check_ext(file, (".pdf",))
    workdir = tempfile.mkdtemp(prefix="split_")
    try:
        from pypdf import PdfReader, PdfWriter

        src = await _save(file, Path(workdir) / "entrada.pdf")
        reader = PdfReader(str(src))
        total = len(reader.pages)
        parsed = _parse_ranges(ranges, total)
        stem = Path(file.filename or "documento").stem
        parts: list[Path] = []
        for start, end in parsed:
            writer = PdfWriter()
            for page in range(start - 1, end):
                writer.add_page(reader.pages[page])
            label = f"{start}" if start == end else f"{start}-{end}"
            out = Path(workdir) / f"{stem}_p{label}.pdf"
            with out.open("wb") as fh:
                writer.write(fh)
            writer.close()
            parts.append(out)
        if len(parts) == 1:
            return _respond(parts[0], workdir, "application/pdf")
        zip_path = Path(workdir) / f"{stem}_dividido.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in parts:
                zf.write(p, p.name)
    except HTTPException:
        _cleanup(workdir)
        raise
    except Exception as exc:  # noqa: BLE001
        _cleanup(workdir)
        raise HTTPException(status_code=500, detail=f"Error al dividir: {exc}") from exc
    return _respond(zip_path, workdir, "application/zip")


@router.post("/images-to-pdf")
async def images_to_pdf(files: List[UploadFile] = File(...)):
    if not files:
        raise HTTPException(status_code=400, detail="Selecciona al menos una imagen")
    for f in files:
        _check_ext(f, (".jpg", ".jpeg", ".png", ".webp"))
    workdir = tempfile.mkdtemp(prefix="img_")
    try:
        from PIL import Image

        paths: list[Path] = []
        for i, f in enumerate(files):
            suffix = Path(f.filename or f"img_{i}.jpg").suffix
            paths.append(await _save(f, Path(workdir) / f"in_{i}{suffix}"))
        images = [Image.open(p).convert("RGB") for p in paths]
        out = Path(workdir) / "imagenes.pdf"
        images[0].save(out, "PDF", save_all=True, append_images=images[1:])
        for im in images:
            im.close()
    except HTTPException:
        _cleanup(workdir)
        raise
    except Exception as exc:  # noqa: BLE001
        _cleanup(workdir)
        raise HTTPException(status_code=500, detail=f"Error al generar el PDF: {exc}") from exc
    return _respond(out, workdir, "application/pdf")


_IMG_INPUTS = (".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff")


def _zip_dedup(paths: list[Path], zip_path: Path) -> None:
    used: dict[str, int] = {}
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in paths:
            arc = p.name
            if arc in used:
                used[arc] += 1
                arc = f"{p.stem}_{used[p.name]}{p.suffix}"
            else:
                used[arc] = 0
            zf.write(p, arc)


@router.post("/convert-image")
async def convert_image(files: List[UploadFile] = File(...), target: str = Form("png")):
    if not files:
        raise HTTPException(status_code=400, detail="Selecciona al menos una imagen")
    target = target.lower()
    if target not in ("jpg", "jpeg", "png"):
        raise HTTPException(status_code=400, detail="Formato de destino no soportado")
    out_ext = "png" if target == "png" else "jpg"
    for f in files:
        _check_ext(f, _IMG_INPUTS)
    workdir = tempfile.mkdtemp(prefix="conv_")
    try:
        from PIL import Image

        outs: list[Path] = []
        for i, f in enumerate(files):
            suffix = Path(f.filename or f"img_{i}").suffix
            src = await _save(f, Path(workdir) / f"in_{i}{suffix}")
            im = Image.open(src)
            stem = Path(f.filename or f"imagen_{i}").stem
            out = Path(workdir) / f"{stem}.{out_ext}"
            if out_ext == "png":
                # Lossless: preserve alpha/palette exactly where present.
                im.save(out, "PNG", optimize=True)
            else:
                # JPEG has no alpha — flatten onto white, then encode near-lossless.
                if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
                    rgba = im.convert("RGBA")
                    bg = Image.new("RGB", rgba.size, (255, 255, 255))
                    bg.paste(rgba, mask=rgba.split()[-1])
                    im = bg
                else:
                    im = im.convert("RGB")
                im.save(out, "JPEG", quality=95, subsampling=0)  # keep quality
            im.close()
            outs.append(out)
        if len(outs) == 1:
            media = "image/png" if out_ext == "png" else "image/jpeg"
            return _respond(outs[0], workdir, media)
        zip_path = Path(workdir) / f"imagenes-{out_ext}.zip"
        _zip_dedup(outs, zip_path)
    except HTTPException:
        _cleanup(workdir)
        raise
    except Exception as exc:  # noqa: BLE001
        _cleanup(workdir)
        raise HTTPException(status_code=500, detail=f"Error al convertir: {exc}") from exc
    return _respond(zip_path, workdir, "application/zip")


_AUDIO_INPUTS = (".mp3", ".wav", ".m4a", ".flac", ".aac", ".ogg", ".oga", ".opus", ".wma")
_VIDEO_INPUTS = (".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".mpeg", ".mpg", ".wmv", ".flv")
_AUDIO_CODECS: dict[str, list[str]] = {
    "mp3": ["-c:a", "libmp3lame", "-q:a", "2"],   # high-quality VBR (~190 kbps)
    "wav": ["-c:a", "pcm_s16le"],                  # uncompressed PCM
    "flac": ["-c:a", "flac"],                       # lossless
    "m4a": ["-c:a", "aac", "-b:a", "192k"],
}
_AUDIO_MEDIA = {"mp3": "audio/mpeg", "wav": "audio/wav", "flac": "audio/flac", "m4a": "audio/mp4"}
_BITRATES = {"128", "192", "320"}
_TIME_RE = re.compile(r"^\d+(:\d{1,2}){0,2}(\.\d+)?$")  # 90, 1:30, 01:02:03, 12.5


def _audio_codec_args(target: str, bitrate: str) -> list[str]:
    if target == "mp3":
        return ["-c:a", "libmp3lame", "-b:a", f"{bitrate}k"]
    if target == "m4a":
        return ["-c:a", "aac", "-b:a", f"{bitrate}k"]
    if target == "wav":
        return ["-c:a", "pcm_s16le"]
    return ["-c:a", "flac"]  # lossless — bitrate ignored


@router.post("/convert-audio")
async def convert_audio(
    files: List[UploadFile] = File(...),
    target: str = Form("mp3"),
    bitrate: str = Form("192"),
    normalize: str = Form("false"),
    start: str = Form(""),
    end: str = Form(""),
):
    """Convert audio / extract audio from video via ffmpeg, with optional bitrate,
    loudness normalisation (EBU R128) and trim (start/end)."""
    if not files:
        raise HTTPException(status_code=400, detail="Selecciona al menos un archivo")
    target = target.lower()
    if target not in _AUDIO_MEDIA:
        raise HTTPException(status_code=400, detail="Formato de destino no soportado")
    if bitrate not in _BITRATES:
        bitrate = "192"
    start, end = start.strip(), end.strip()
    for label, value in (("inicio", start), ("fin", end)):
        if value and not _TIME_RE.match(value):
            raise HTTPException(status_code=400, detail=f"Tiempo de {label} no válido: {value}")
    normalize_on = normalize.strip().lower() in ("1", "true", "yes", "on")
    for f in files:
        _check_ext(f, _AUDIO_INPUTS + _VIDEO_INPUTS)

    seek: list[str] = []
    if start:
        seek += ["-ss", start]
    if end:
        seek += ["-to", end]
    filters = ["-af", "loudnorm=I=-16:TP=-1.5:LRA=11"] if normalize_on else []

    workdir = tempfile.mkdtemp(prefix="audio_")
    try:
        outs: list[Path] = []
        for i, f in enumerate(files):
            suffix = Path(f.filename or f"in_{i}").suffix
            src = await _save(f, Path(workdir) / f"in_{i}{suffix}")
            stem = Path(f.filename or f"audio_{i}").stem
            out = Path(workdir) / f"{stem}.{target}"

            def _run(src: Path = src, out: Path = out):
                cmd = [
                    _ffmpeg_bin(), "-y", *seek, "-i", str(src), "-vn",
                    *filters, *_audio_codec_args(target, bitrate), str(out),
                ]
                subprocess.run(cmd, check=True, capture_output=True, timeout=600)

            await asyncio.to_thread(_run)
            if not out.exists() or out.stat().st_size == 0:
                raise HTTPException(status_code=500, detail="La conversión no produjo audio")
            outs.append(out)
        if len(outs) == 1:
            return _respond(outs[0], workdir, _AUDIO_MEDIA[target])
        zip_path = Path(workdir) / f"audio-{target}.zip"
        _zip_dedup(outs, zip_path)
    except HTTPException:
        _cleanup(workdir)
        raise
    except subprocess.CalledProcessError as exc:
        _cleanup(workdir)
        msg = exc.stderr.decode("utf-8", "ignore")[-300:] if exc.stderr else str(exc)
        raise HTTPException(status_code=500, detail=f"Error de ffmpeg: {msg}") from exc
    except Exception as exc:  # noqa: BLE001
        _cleanup(workdir)
        raise HTTPException(status_code=500, detail=f"Error al convertir: {exc}") from exc
    return _respond(zip_path, workdir, "application/zip")
