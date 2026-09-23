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

router = APIRouter(prefix="/tools", tags=["tools"])

MAX_BYTES = 100 * 1024 * 1024  # 100 MB per file


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


def _respond(path: Path, workdir: str, media_type: str) -> FileResponse:
    return FileResponse(
        path,
        media_type=media_type,
        filename=path.name,
        headers={"Content-Disposition": f'attachment; filename="{path.name}"'},
        background=BackgroundTask(_cleanup, workdir),  # temp files deleted after the response
    )


def _soffice(src: Path, outdir: Path) -> Path:
    subprocess.run(
        ["soffice", "--headless", "--norestore", "--convert-to", "pdf", "--outdir", str(outdir), str(src)],
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
async def word_to_pdf(file: UploadFile = File(...)):
    _check_ext(file, (".docx", ".doc", ".odt", ".rtf"))
    workdir = tempfile.mkdtemp(prefix="w2p_")
    try:
        src = await _save(file, Path(workdir) / Path(file.filename or "documento.docx").name)
        out = await asyncio.to_thread(_soffice, src, Path(workdir))
    except HTTPException:
        _cleanup(workdir)
        raise
    except Exception as exc:  # noqa: BLE001
        _cleanup(workdir)
        raise HTTPException(status_code=500, detail=f"Error al convertir: {exc}") from exc
    return _respond(out, workdir, "application/pdf")


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
