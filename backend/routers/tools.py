"""Local file tooling — chunked uploads to disk + on-disk processing. No external services.

Upload flow (never loads a whole file into RAM):
  PUT  /api/tools/upload/{upload_id}/{index}   raw chunk bytes, streamed to disk
  POST /api/tools/upload/{upload_id}/complete  reassemble parts -> single file, size-checked
Each processing endpoint then takes JSON {"upload_ids": [...], ...options} and reads the
already-assembled files straight from disk. Temp dirs are removed after the response or on error.
"""
import asyncio
import glob
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Iterable

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from starlette.background import BackgroundTask

router = APIRouter(prefix="/tools", tags=["tools"])

MB = 1024 * 1024
CATEGORY_LIMITS = {
    "documents": 150 * MB,
    "image": 500 * MB,
    "audio": 300 * MB,
    "video": 8192 * MB,
}
DEFAULT_LIMIT = 150 * MB

STAGE_ROOT = Path(tempfile.gettempdir()) / "tallerpdf_uploads"
_COPY_BUF = 4 * MB


# ---------------------------------------------------------------------------- binaries
def _ffmpeg_bin() -> str:
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


def _soffice_bin() -> str:
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
    return "soffice"


# ---------------------------------------------------------------------------- staging
def _safe_id(upload_id: str) -> str:
    clean = re.sub(r"[^a-zA-Z0-9_-]", "", upload_id)[:64]
    if not clean:
        raise HTTPException(status_code=400, detail="Identificador de subida no válido")
    return clean


def _safe_name(filename: str) -> str:
    base = Path(filename or "archivo").name
    base = re.sub(r"[^\w.\-]+", "_", base).strip("._") or "archivo"
    return base[:200]


def _stage_root(upload_id: str) -> Path:
    return STAGE_ROOT / _safe_id(upload_id)


def _cleanup_dirs(dirs: Iterable[Path]) -> None:
    for d in dirs:
        shutil.rmtree(d, ignore_errors=True)


class CompleteRequest(BaseModel):
    filename: str
    total: int
    category: str = "documents"


@router.put("/upload/{upload_id}/{index}")
async def upload_chunk(upload_id: str, index: int, request: Request):
    """Stream one chunk straight to disk — the body is never buffered whole in memory."""
    parts = _stage_root(upload_id) / "parts"
    parts.mkdir(parents=True, exist_ok=True)
    part = parts / f"{index:08d}.part"
    with part.open("wb") as fh:
        async for block in request.stream():
            fh.write(block)
    return {"ok": True, "index": index}


@router.post("/upload/{upload_id}/complete")
async def upload_complete(upload_id: str, body: CompleteRequest):
    root = _stage_root(upload_id)
    parts_dir = root / "parts"
    parts = sorted(parts_dir.glob("*.part"))
    if not parts or len(parts) != body.total:
        _cleanup_dirs([root])
        raise HTTPException(status_code=400, detail="Subida incompleta: faltan bloques")
    limit = CATEGORY_LIMITS.get(body.category, DEFAULT_LIMIT)
    total_size = sum(p.stat().st_size for p in parts)
    if total_size > limit:
        _cleanup_dirs([root])
        raise HTTPException(
            status_code=413,
            detail=f"El archivo supera el límite de {limit // MB} MB para esta categoría",
        )
    assembled = root / "assembled"
    assembled.mkdir(parents=True, exist_ok=True)
    out = assembled / _safe_name(body.filename)
    with out.open("wb") as writer:  # streamed concat, constant memory
        for p in parts:
            with p.open("rb") as reader:
                shutil.copyfileobj(reader, writer, _COPY_BUF)
            p.unlink(missing_ok=True)
    shutil.rmtree(parts_dir, ignore_errors=True)
    return {"upload_id": _safe_id(upload_id), "filename": out.name, "size": total_size}


def _resolve_inputs(upload_ids: list[str]) -> tuple[list[Path], list[Path]]:
    """Map upload ids -> assembled file paths. Returns (paths, stage_dirs_to_cleanup)."""
    if not upload_ids:
        raise HTTPException(status_code=400, detail="Sube al menos un archivo")
    paths: list[Path] = []
    stages: list[Path] = []
    for uid in upload_ids:
        root = _stage_root(uid)
        stages.append(root)
        assembled = root / "assembled"
        found = sorted(assembled.glob("*")) if assembled.is_dir() else []
        if not found:
            _cleanup_dirs(stages)
            raise HTTPException(status_code=400, detail="Subida no encontrada o incompleta")
        paths.append(found[0])
    return paths, stages


def _check_name(name: str, allowed: tuple[str, ...]) -> None:
    if not name.lower().endswith(allowed):
        raise HTTPException(
            status_code=400,
            detail=f"Formato no soportado: {name}. Se esperaba {', '.join(allowed)}",
        )


def _respond(path: Path, cleanup: Iterable[Path], media_type: str, extra_headers: dict | None = None) -> FileResponse:
    headers = {"Content-Disposition": f'attachment; filename="{path.name}"'}
    if extra_headers:
        headers.update(extra_headers)
    return FileResponse(
        path,
        media_type=media_type,
        filename=path.name,
        headers=headers,
        background=BackgroundTask(_cleanup_dirs, list(cleanup)),
    )


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


# ---------------------------------------------------------------------------- request model
class ProcessRequest(BaseModel):
    upload_ids: list[str] = []
    target: str | None = None
    scale: str | None = None
    quality: str | None = None
    bitrate: str | None = None
    normalize: bool = False
    start: str | None = None
    end: str | None = None
    ranges: str | None = None
    level: str | None = None
    fmt: str | None = None
    interval: str | None = None


def _opt(value: str | None, default: str = "") -> str:
    return value if value is not None else default


# ---------------------------------------------------------------------------- documents
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
async def word_to_pdf(body: ProcessRequest):
    inputs, stages = _resolve_inputs(body.upload_ids)
    for p in inputs:
        _check_name(p.name, (".docx", ".doc", ".odt", ".rtf"))
    workdir = Path(tempfile.mkdtemp(prefix="w2p_"))
    cleanup = [*stages, workdir]
    try:
        pdfs: list[Path] = []
        for i, src in enumerate(inputs):
            sub = workdir / f"src_{i}"
            sub.mkdir()
            out = await asyncio.to_thread(_soffice, src, sub)
            final = workdir / (src.stem + ".pdf")
            shutil.move(str(out), str(final))
            pdfs.append(final)
        if len(pdfs) == 1:
            return _respond(pdfs[0], cleanup, "application/pdf")
        zip_path = workdir / "documentos-pdf.zip"
        _zip_dedup(pdfs, zip_path)
    except HTTPException:
        _cleanup_dirs(cleanup)
        raise
    except Exception as exc:  # noqa: BLE001
        _cleanup_dirs(cleanup)
        raise HTTPException(status_code=500, detail=f"Error al convertir: {exc}") from exc
    return _respond(zip_path, cleanup, "application/zip")


def _pdf_to_docx(src: Path, out: Path):
    from pdf2docx import Converter

    cv = Converter(str(src))
    try:
        cv.convert(str(out))
    finally:
        cv.close()


@router.post("/pdf-to-word")
async def pdf_to_word(body: ProcessRequest):
    inputs, stages = _resolve_inputs(body.upload_ids)
    src = inputs[0]
    _check_name(src.name, (".pdf",))
    workdir = Path(tempfile.mkdtemp(prefix="p2w_"))
    cleanup = [*stages, workdir]
    try:
        out = workdir / (src.stem + ".docx")
        await asyncio.to_thread(_pdf_to_docx, src, out)
        if not out.exists():
            raise HTTPException(status_code=500, detail="La conversión no produjo un DOCX")
    except HTTPException:
        _cleanup_dirs(cleanup)
        raise
    except Exception as exc:  # noqa: BLE001
        _cleanup_dirs(cleanup)
        raise HTTPException(status_code=500, detail=f"Error al convertir: {exc}") from exc
    return _respond(
        out, cleanup, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )


@router.post("/merge-pdf")
async def merge_pdf(body: ProcessRequest):
    inputs, stages = _resolve_inputs(body.upload_ids)
    if len(inputs) < 2:
        _cleanup_dirs(stages)
        raise HTTPException(status_code=400, detail="Selecciona al menos 2 archivos PDF")
    for p in inputs:
        _check_name(p.name, (".pdf",))
    workdir = Path(tempfile.mkdtemp(prefix="merge_"))
    cleanup = [*stages, workdir]
    try:
        from pypdf import PdfWriter

        writer = PdfWriter()
        for src in inputs:
            writer.append(str(src))
        out = workdir / "documento-unido.pdf"
        with out.open("wb") as fh:
            writer.write(fh)
        writer.close()
    except HTTPException:
        _cleanup_dirs(cleanup)
        raise
    except Exception as exc:  # noqa: BLE001
        _cleanup_dirs(cleanup)
        raise HTTPException(status_code=500, detail=f"Error al unir: {exc}") from exc
    return _respond(out, cleanup, "application/pdf")


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
            raise HTTPException(status_code=400, detail=f"Rango fuera de los límites (1-{total}): {part}")
        out.append((start, end))
    if not out:
        raise HTTPException(status_code=400, detail="Indica al menos un rango de páginas")
    return out


@router.post("/split-pdf")
async def split_pdf(body: ProcessRequest):
    inputs, stages = _resolve_inputs(body.upload_ids)
    src = inputs[0]
    _check_name(src.name, (".pdf",))
    workdir = Path(tempfile.mkdtemp(prefix="split_"))
    cleanup = [*stages, workdir]
    try:
        from pypdf import PdfReader, PdfWriter

        reader = PdfReader(str(src))
        total = len(reader.pages)
        parsed = _parse_ranges(_opt(body.ranges), total)
        stem = src.stem
        parts: list[Path] = []
        for start, end in parsed:
            writer = PdfWriter()
            for page in range(start - 1, end):
                writer.add_page(reader.pages[page])
            label = f"{start}" if start == end else f"{start}-{end}"
            out = workdir / f"{stem}_p{label}.pdf"
            with out.open("wb") as fh:
                writer.write(fh)
            writer.close()
            parts.append(out)
        if len(parts) == 1:
            return _respond(parts[0], cleanup, "application/pdf")
        zip_path = workdir / f"{stem}_dividido.zip"
        _zip_dedup(parts, zip_path)
    except HTTPException:
        _cleanup_dirs(cleanup)
        raise
    except Exception as exc:  # noqa: BLE001
        _cleanup_dirs(cleanup)
        raise HTTPException(status_code=500, detail=f"Error al dividir: {exc}") from exc
    return _respond(zip_path, cleanup, "application/zip")


_GS_QUALITY = {"ligera": "/printer", "recomendada": "/ebook", "maxima": "/screen"}


@router.post("/compress-pdf")
async def compress_pdf(body: ProcessRequest):
    inputs, stages = _resolve_inputs(body.upload_ids)
    src = inputs[0]
    _check_name(src.name, (".pdf",))
    quality = _GS_QUALITY.get(_opt(body.level, "recomendada"), "/ebook")
    workdir = Path(tempfile.mkdtemp(prefix="comp_"))
    cleanup = [*stages, workdir]
    try:
        original = src.stat().st_size
        out = workdir / (src.stem + "_comprimido.pdf")

        def _gs():
            subprocess.run(
                [
                    _gs_bin(), "-sDEVICE=pdfwrite", "-dCompatibilityLevel=1.4",
                    f"-dPDFSETTINGS={quality}", "-dNOPAUSE", "-dQUIET", "-dBATCH",
                    "-dDetectDuplicateImages=true", f"-sOutputFile={out}", str(src),
                ],
                check=True, capture_output=True, timeout=600,
            )

        await asyncio.to_thread(_gs)
        if not out.exists() or out.stat().st_size == 0:
            raise HTTPException(status_code=500, detail="La compresión no produjo un PDF")
        compressed = out.stat().st_size
        if compressed >= original:
            shutil.copyfile(src, out)
            compressed = original
        reduction = 0 if original == 0 else round((1 - compressed / original) * 100)
    except HTTPException:
        _cleanup_dirs(cleanup)
        raise
    except Exception as exc:  # noqa: BLE001
        _cleanup_dirs(cleanup)
        raise HTTPException(status_code=500, detail=f"Error al comprimir: {exc}") from exc
    return _respond(
        out, cleanup, "application/pdf",
        extra_headers={
            "X-Original-Size": str(original),
            "X-Compressed-Size": str(compressed),
            "X-Reduction-Percent": str(reduction),
        },
    )


# ---------------------------------------------------------------------------- images
@router.post("/images-to-pdf")
async def images_to_pdf(body: ProcessRequest):
    inputs, stages = _resolve_inputs(body.upload_ids)
    for p in inputs:
        _check_name(p.name, (".jpg", ".jpeg", ".png", ".webp"))
    workdir = Path(tempfile.mkdtemp(prefix="img_"))
    cleanup = [*stages, workdir]
    try:
        from PIL import Image

        images = [Image.open(p).convert("RGB") for p in inputs]
        out = workdir / "imagenes.pdf"
        images[0].save(out, "PDF", save_all=True, append_images=images[1:])
        for im in images:
            im.close()
    except HTTPException:
        _cleanup_dirs(cleanup)
        raise
    except Exception as exc:  # noqa: BLE001
        _cleanup_dirs(cleanup)
        raise HTTPException(status_code=500, detail=f"Error al generar el PDF: {exc}") from exc
    return _respond(out, cleanup, "application/pdf")


_IMG_INPUTS = (".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff")


@router.post("/convert-image")
async def convert_image(body: ProcessRequest):
    inputs, stages = _resolve_inputs(body.upload_ids)
    target = _opt(body.target, "png").lower()
    if target not in ("jpg", "jpeg", "png"):
        _cleanup_dirs(stages)
        raise HTTPException(status_code=400, detail="Formato de destino no soportado")
    out_ext = "png" if target == "png" else "jpg"
    for p in inputs:
        _check_name(p.name, _IMG_INPUTS)
    workdir = Path(tempfile.mkdtemp(prefix="conv_"))
    cleanup = [*stages, workdir]
    try:
        from PIL import Image

        outs: list[Path] = []
        for src in inputs:
            im = Image.open(src)
            out = workdir / f"{src.stem}.{out_ext}"
            if out_ext == "png":
                im.save(out, "PNG", optimize=True)
            else:
                if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
                    rgba = im.convert("RGBA")
                    bg = Image.new("RGB", rgba.size, (255, 255, 255))
                    bg.paste(rgba, mask=rgba.split()[-1])
                    im = bg
                else:
                    im = im.convert("RGB")
                im.save(out, "JPEG", quality=95, subsampling=0)
            im.close()
            outs.append(out)
        if len(outs) == 1:
            return _respond(outs[0], cleanup, "image/png" if out_ext == "png" else "image/jpeg")
        zip_path = workdir / f"imagenes-{out_ext}.zip"
        _zip_dedup(outs, zip_path)
    except HTTPException:
        _cleanup_dirs(cleanup)
        raise
    except Exception as exc:  # noqa: BLE001
        _cleanup_dirs(cleanup)
        raise HTTPException(status_code=500, detail=f"Error al convertir: {exc}") from exc
    return _respond(zip_path, cleanup, "application/zip")


# ---------------------------------------------------------------------------- audio / video
_AUDIO_INPUTS = (".mp3", ".wav", ".m4a", ".flac", ".aac", ".ogg", ".oga", ".opus", ".wma")
_VIDEO_INPUTS = (".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".mpeg", ".mpg", ".wmv", ".flv")
_AUDIO_MEDIA = {"mp3": "audio/mpeg", "wav": "audio/wav", "flac": "audio/flac", "m4a": "audio/mp4"}
_BITRATES = {"128", "192", "320"}
_TIME_RE = re.compile(r"^\d+(:\d{1,2}){0,2}(\.\d+)?$")


def _audio_codec_args(target: str, bitrate: str) -> list[str]:
    if target == "mp3":
        return ["-c:a", "libmp3lame", "-b:a", f"{bitrate}k"]
    if target == "m4a":
        return ["-c:a", "aac", "-b:a", f"{bitrate}k"]
    if target == "wav":
        return ["-c:a", "pcm_s16le"]
    return ["-c:a", "flac"]


@router.post("/convert-audio")
async def convert_audio(body: ProcessRequest):
    inputs, stages = _resolve_inputs(body.upload_ids)
    target = _opt(body.target, "mp3").lower()
    if target not in _AUDIO_MEDIA:
        _cleanup_dirs(stages)
        raise HTTPException(status_code=400, detail="Formato de destino no soportado")
    bitrate = body.bitrate if body.bitrate in _BITRATES else "192"
    start, end = _opt(body.start).strip(), _opt(body.end).strip()
    for label, value in (("inicio", start), ("fin", end)):
        if value and not _TIME_RE.match(value):
            _cleanup_dirs(stages)
            raise HTTPException(status_code=400, detail=f"Tiempo de {label} no válido: {value}")
    for p in inputs:
        _check_name(p.name, _AUDIO_INPUTS + _VIDEO_INPUTS)
    seek: list[str] = []
    if start:
        seek += ["-ss", start]
    if end:
        seek += ["-to", end]
    filters = ["-af", "loudnorm=I=-16:TP=-1.5:LRA=11"] if body.normalize else []
    workdir = Path(tempfile.mkdtemp(prefix="audio_"))
    cleanup = [*stages, workdir]
    try:
        outs: list[Path] = []
        for src in inputs:
            out = workdir / f"{src.stem}.{target}"

            def _run(src: Path = src, out: Path = out):
                cmd = [
                    _ffmpeg_bin(), "-y", *seek, "-i", str(src), "-vn",
                    *filters, *_audio_codec_args(target, bitrate), str(out),
                ]
                subprocess.run(cmd, check=True, capture_output=True, timeout=1800)

            await asyncio.to_thread(_run)
            if not out.exists() or out.stat().st_size == 0:
                raise HTTPException(status_code=500, detail="La conversión no produjo audio")
            outs.append(out)
        if len(outs) == 1:
            return _respond(outs[0], cleanup, _AUDIO_MEDIA[target])
        zip_path = workdir / f"audio-{target}.zip"
        _zip_dedup(outs, zip_path)
    except HTTPException:
        _cleanup_dirs(cleanup)
        raise
    except subprocess.CalledProcessError as exc:
        _cleanup_dirs(cleanup)
        msg = exc.stderr.decode("utf-8", "ignore")[-300:] if exc.stderr else str(exc)
        raise HTTPException(status_code=500, detail=f"Error de ffmpeg: {msg}") from exc
    except Exception as exc:  # noqa: BLE001
        _cleanup_dirs(cleanup)
        raise HTTPException(status_code=500, detail=f"Error al convertir: {exc}") from exc
    return _respond(zip_path, cleanup, "application/zip")


@router.post("/merge-audio")
async def merge_audio(body: ProcessRequest):
    inputs, stages = _resolve_inputs(body.upload_ids)
    if len(inputs) < 2:
        _cleanup_dirs(stages)
        raise HTTPException(status_code=400, detail="Selecciona al menos 2 archivos")
    target = _opt(body.target, "mp3").lower()
    if target not in _AUDIO_MEDIA:
        _cleanup_dirs(stages)
        raise HTTPException(status_code=400, detail="Formato de destino no soportado")
    bitrate = body.bitrate if body.bitrate in _BITRATES else "192"
    for p in inputs:
        _check_name(p.name, _AUDIO_INPUTS + _VIDEO_INPUTS)
    workdir = Path(tempfile.mkdtemp(prefix="merge_audio_"))
    cleanup = [*stages, workdir]
    try:
        out = workdir / f"pistas-unidas.{target}"
        n = len(inputs)
        concat_in = "".join(f"[{i}:a]" for i in range(n))
        filt = f"{concat_in}concat=n={n}:v=0:a=1[c]"
        out_label = "[c]"
        if body.normalize:
            filt += ";[c]loudnorm=I=-16:TP=-1.5:LRA=11[o]"
            out_label = "[o]"

        def _run():
            cmd = [_ffmpeg_bin(), "-y"]
            for p in inputs:
                cmd += ["-i", str(p)]
            cmd += ["-filter_complex", filt, "-map", out_label, *_audio_codec_args(target, bitrate), str(out)]
            subprocess.run(cmd, check=True, capture_output=True, timeout=1800)

        await asyncio.to_thread(_run)
        if not out.exists() or out.stat().st_size == 0:
            raise HTTPException(status_code=500, detail="La unión no produjo audio")
    except HTTPException:
        _cleanup_dirs(cleanup)
        raise
    except subprocess.CalledProcessError as exc:
        _cleanup_dirs(cleanup)
        msg = exc.stderr.decode("utf-8", "ignore")[-300:] if exc.stderr else str(exc)
        raise HTTPException(status_code=500, detail=f"Error de ffmpeg: {msg}") from exc
    except Exception as exc:  # noqa: BLE001
        _cleanup_dirs(cleanup)
        raise HTTPException(status_code=500, detail=f"Error al unir: {exc}") from exc
    return _respond(out, cleanup, _AUDIO_MEDIA[target])


_VIDEO_OUT = {
    "mp4": "video/mp4",
    "mov": "video/quicktime",
    "avi": "video/x-msvideo",
    "mkv": "video/x-matroska",
}
_VIDEO_SCALES = {"original", "2160", "1440", "1080", "720", "480", "360"}
_VIDEO_CRF = {"ligera": "20", "recomendada": "23", "maxima": "28"}


@router.post("/convert-video")
async def convert_video(body: ProcessRequest):
    inputs, stages = _resolve_inputs(body.upload_ids)
    target = _opt(body.target, "mp4").lower()
    if target not in _VIDEO_OUT:
        _cleanup_dirs(stages)
        raise HTTPException(status_code=400, detail="Formato de destino no soportado")
    scale = body.scale if body.scale in _VIDEO_SCALES else "original"
    crf = _VIDEO_CRF.get(_opt(body.quality, "recomendada"), "23")
    start, end = _opt(body.start).strip(), _opt(body.end).strip()
    for label, value in (("inicio", start), ("fin", end)):
        if value and not _TIME_RE.match(value):
            _cleanup_dirs(stages)
            raise HTTPException(status_code=400, detail=f"Tiempo de {label} no válido: {value}")
    seek: list[str] = []
    if start:
        seek += ["-ss", start]
    if end:
        seek += ["-to", end]
    for p in inputs:
        _check_name(p.name, _VIDEO_INPUTS)
    workdir = Path(tempfile.mkdtemp(prefix="video_"))
    cleanup = [*stages, workdir]
    try:
        outs: list[Path] = []
        for src in inputs:
            out = workdir / f"{src.stem}.{target}"
            vf = [] if scale == "original" else ["-vf", f"scale=-2:{scale}"]
            faststart = ["-movflags", "+faststart"] if target == "mp4" else []

            def _run(src: Path = src, out: Path = out, vf: list[str] = vf, fs: list[str] = faststart):
                cmd = [
                    _ffmpeg_bin(), "-y", *seek, "-i", str(src), *vf,
                    "-c:v", "libx264", "-preset", "medium", "-crf", crf,
                    "-c:a", "aac", "-b:a", "128k", *fs, str(out),
                ]
                subprocess.run(cmd, check=True, capture_output=True, timeout=3600)

            await asyncio.to_thread(_run)
            if not out.exists() or out.stat().st_size == 0:
                raise HTTPException(status_code=500, detail="La conversión no produjo vídeo")
            outs.append(out)
        if len(outs) == 1:
            return _respond(outs[0], cleanup, _VIDEO_OUT[target])
        zip_path = workdir / f"video-{target}.zip"
        _zip_dedup(outs, zip_path)
    except HTTPException:
        _cleanup_dirs(cleanup)
        raise
    except subprocess.CalledProcessError as exc:
        _cleanup_dirs(cleanup)
        msg = exc.stderr.decode("utf-8", "ignore")[-300:] if exc.stderr else str(exc)
        raise HTTPException(status_code=500, detail=f"Error de ffmpeg: {msg}") from exc
    except Exception as exc:  # noqa: BLE001
        _cleanup_dirs(cleanup)
        raise HTTPException(status_code=500, detail=f"Error al convertir: {exc}") from exc
    return _respond(zip_path, cleanup, "application/zip")


@router.post("/extract-frames")
async def extract_frames(body: ProcessRequest):
    inputs, stages = _resolve_inputs(body.upload_ids)
    src = inputs[0]
    _check_name(src.name, _VIDEO_INPUTS)
    fmt = _opt(body.fmt, "jpg").lower()
    if fmt not in ("jpg", "jpeg", "png"):
        _cleanup_dirs(stages)
        raise HTTPException(status_code=400, detail="Formato de imagen no soportado")
    ext = "png" if fmt == "png" else "jpg"
    try:
        step = float(_opt(body.interval, "1").replace(",", "."))
    except ValueError as exc:
        _cleanup_dirs(stages)
        raise HTTPException(status_code=400, detail="Intervalo no válido") from exc
    if step <= 0:
        _cleanup_dirs(stages)
        raise HTTPException(status_code=400, detail="El intervalo debe ser mayor que 0")
    step = max(step, 0.1)
    workdir = Path(tempfile.mkdtemp(prefix="frames_"))
    cleanup = [*stages, workdir]
    try:
        framedir = workdir / "frames"
        framedir.mkdir()
        pattern = str(framedir / f"{src.stem}_%04d.{ext}")

        def _run():
            cmd = [_ffmpeg_bin(), "-y", "-i", str(src), "-vf", f"fps=1/{step}"]
            if ext == "jpg":
                cmd += ["-q:v", "2"]
            cmd += [pattern]
            subprocess.run(cmd, check=True, capture_output=True, timeout=1800)

        await asyncio.to_thread(_run)
        frames = sorted(framedir.glob(f"*.{ext}"))
        if not frames:
            raise HTTPException(status_code=500, detail="No se extrajeron fotogramas")
        zip_path = workdir / f"fotogramas-{ext}.zip"
        _zip_dedup(frames, zip_path)
    except HTTPException:
        _cleanup_dirs(cleanup)
        raise
    except subprocess.CalledProcessError as exc:
        _cleanup_dirs(cleanup)
        msg = exc.stderr.decode("utf-8", "ignore")[-300:] if exc.stderr else str(exc)
        raise HTTPException(status_code=500, detail=f"Error de ffmpeg: {msg}") from exc
    except Exception as exc:  # noqa: BLE001
        _cleanup_dirs(cleanup)
        raise HTTPException(status_code=500, detail=f"Error al extraer: {exc}") from exc
    return _respond(zip_path, cleanup, "application/zip")
